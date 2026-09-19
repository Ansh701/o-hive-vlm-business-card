from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import Settings
from backend.app.inference import BusinessCardLead, InferenceError
from backend.app.logging import get_logger
from backend.app.models import Batch, BatchStatus, Lead, LeadStatus
from backend.app.normalization import normalize_email, normalize_phone, normalize_text
from backend.app.uploads import (
    UploadValidationError,
    display_filename,
    validate_image,
)

logger = get_logger(__name__)


class Extractor(Protocol):
    async def extract(self, image: bytes, media_type: str) -> BusinessCardLead: ...


class ServiceError(RuntimeError):
    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


async def get_batch_or_error(
    session: AsyncSession, batch_id: UUID, *, for_update: bool = False
) -> Batch:
    statement = select(Batch).where(Batch.id == batch_id)
    if for_update:
        statement = statement.with_for_update()
    batch = await session.scalar(statement)
    if batch is None:
        raise ServiceError(404, "batch_not_found", "This batch does not exist.")
    return batch


async def get_lead_or_error(session: AsyncSession, lead_id: UUID) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise ServiceError(404, "lead_not_found", "This lead does not exist.")
    return lead


async def _duplicate_exists(session: AsyncSession, batch_id: UUID, digest: str) -> bool:
    existing = await session.scalar(
        select(Lead.id).where(Lead.batch_id == batch_id, Lead.content_sha256 == digest)
    )
    return existing is not None


async def _enforce_batch_capacity(
    session: AsyncSession, batch: Batch, content_size: int, settings: Settings
) -> None:
    lead_count = await session.scalar(
        select(func.count(Lead.id)).where(Lead.batch_id == batch.id)
    )
    if batch.processed_cards >= batch.total_cards or int(lead_count or 0) >= batch.total_cards:
        raise ServiceError(
            409,
            "batch_full",
            "This batch already contains its declared number of cards.",
        )
    used_bytes = await session.scalar(
        select(func.coalesce(func.sum(Lead.source_size_bytes), 0)).where(
            Lead.batch_id == batch.id
        )
    )
    if int(used_bytes or 0) + content_size > settings.max_total_bytes:
        raise ServiceError(
            413,
            "batch_too_large",
            "This card would exceed the batch upload-size limit. Remove another card or resize it.",
        )


async def _reject_duplicate(session: AsyncSession, batch: Batch) -> None:
    """Count a selected duplicate as an isolated failed card without storing it."""
    batch.record_result(LeadStatus.FAILED)
    await session.commit()
    raise ServiceError(
        409, "duplicate_card", "This image is already present in the current batch."
    )


async def _enforce_daily_cap(session: AsyncSession, settings: Settings) -> None:
    start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    invoked = await session.scalar(
        select(func.count(Lead.id)).where(
            Lead.model_invoked.is_(True), Lead.created_at >= start_of_day
        )
    )
    if int(invoked or 0) >= settings.max_daily_cards:
        raise ServiceError(
            429,
            "daily_card_limit",
            "Today's public-demo inference allowance has been reached. Try again tomorrow.",
        )


async def _record_invalid_upload(
    session: AsyncSession,
    batch: Batch,
    filename: str,
    content: bytes,
    error: UploadValidationError,
) -> None:
    digest = hashlib.sha256(content).hexdigest()
    if await _duplicate_exists(session, batch.id, digest):
        await _reject_duplicate(session, batch)
    lead = Lead(
        batch_id=batch.id,
        source_filename=display_filename(filename),
        source_size_bytes=len(content),
        content_sha256=digest,
        status=LeadStatus.FAILED,
        warnings=[error.detail],
        error_message=error.detail,
    )
    session.add(lead)
    batch.record_result(LeadStatus.FAILED)
    await session.commit()


def _normalized_fields(result: BusinessCardLead) -> tuple[dict[str, str | None], list[str]]:
    warnings = list(result.warnings)
    email, email_warnings = normalize_email(result.email)
    phone, phone_warnings = normalize_phone(result.phone_number)
    warnings.extend(email_warnings)
    warnings.extend(phone_warnings)
    for field_name, score in result.confidence.items():
        if score < 0.65:
            warnings.append(f"Low confidence: {field_name}")
    fields = {
        "first_name": normalize_text(result.first_name),
        "last_name": normalize_text(result.last_name),
        "job_title": normalize_text(result.job_title),
        "company": normalize_text(result.company),
        "location": normalize_text(result.location),
        "phone_number": phone,
        "email": email,
    }
    return fields, list(dict.fromkeys(warnings))


async def process_card(
    session: AsyncSession,
    *,
    batch_id: UUID,
    filename: str,
    content: bytes,
    settings: Settings,
    extractor: Extractor,
) -> Lead:
    batch = await get_batch_or_error(session, batch_id, for_update=True)
    await _enforce_batch_capacity(session, batch, len(content), settings)

    try:
        image = validate_image(filename, content, settings)
    except UploadValidationError as exc:
        await _record_invalid_upload(session, batch, filename, content, exc)
        raise ServiceError(422, exc.code, exc.detail) from exc

    if await _duplicate_exists(session, batch.id, image.sha256):
        await _reject_duplicate(session, batch)
    await _enforce_daily_cap(session, settings)

    lead = Lead(
        batch_id=batch.id,
        source_filename=image.display_filename,
        source_size_bytes=len(content),
        content_sha256=image.sha256,
        status=LeadStatus.PROCESSING,
        model_invoked=True,
    )
    batch.status = BatchStatus.PROCESSING
    session.add(lead)
    await session.commit()

    inference_started = perf_counter()
    try:
        result = await extractor.extract(image.content, image.media_type)
        fields, warnings = _normalized_fields(result)
        for field_name, value in fields.items():
            setattr(lead, field_name, value)
        lead.warnings = warnings
        if not any(fields.values()):
            lead.status = LeadStatus.FAILED
            lead.error_message = "No contact details could be read confidently from this card."
        elif warnings:
            lead.status = LeadStatus.PARTIAL
        else:
            lead.status = LeadStatus.SUCCESS
    except InferenceError as exc:
        lead.status = LeadStatus.FAILED
        lead.error_message = str(exc)
        lead.warnings = [str(exc)]
        logger.warning(
            "vlm_extraction_failed",
            batch_id=str(batch_id),
            lead_id=str(lead.id),
            source_ref=image.sha256[:12],
            duration_ms=round((perf_counter() - inference_started) * 1000, 1),
            error_category=type(exc).__name__,
        )
    else:
        logger.info(
            "vlm_extraction_completed",
            batch_id=str(batch_id),
            lead_id=str(lead.id),
            source_ref=image.sha256[:12],
            duration_ms=round((perf_counter() - inference_started) * 1000, 1),
            result=lead.status.value,
        )

    batch = await get_batch_or_error(session, batch_id, for_update=True)
    batch.record_result(lead.status)
    await session.commit()
    await session.refresh(lead)
    return lead


async def update_lead(session: AsyncSession, lead: Lead, changes: dict[str, Any]) -> Lead:
    warnings = [warning for warning in lead.warnings if not warning.startswith("Low confidence:")]
    for field_name, value in changes.items():
        if field_name == "email":
            normalized, new_warnings = normalize_email(value)
            if new_warnings:
                raise ServiceError(
                    422,
                    "invalid_email",
                    "Enter a valid email address or leave it blank.",
                )
            value = normalized
        elif field_name == "phone_number":
            normalized, new_warnings = normalize_phone(value)
            if new_warnings == ["Phone format needs review"]:
                raise ServiceError(
                    422,
                    "invalid_phone",
                    "Enter a recognizable phone number or leave it blank.",
                )
            value = normalized
            warnings.extend(new_warnings)
        else:
            value = normalize_text(value)
        setattr(lead, field_name, value)
    lead.warnings = list(dict.fromkeys(warnings))
    if lead.status in {LeadStatus.FAILED, LeadStatus.PARTIAL} and any(
        getattr(lead, field)
        for field in ("first_name", "last_name", "company", "email", "phone_number")
    ):
        lead.status = LeadStatus.PARTIAL if lead.warnings else LeadStatus.SUCCESS
        lead.error_message = None
    await session.commit()
    await session.refresh(lead)
    return lead
