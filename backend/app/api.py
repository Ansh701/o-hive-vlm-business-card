from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings
from backend.app.export import build_workbook, export_filename
from backend.app.models import Batch, Lead, LeadStatus
from backend.app.rate_limit import SlidingWindowLimiter
from backend.app.schemas import BatchCreate, BatchRead, LeadPatch, LeadRead
from backend.app.services import (
    Extractor,
    ServiceError,
    get_batch_or_error,
    get_lead_or_error,
    process_card,
    update_lead,
)


def build_api_router(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    inference_client: Extractor,
    limiter: SlidingWindowLimiter,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    Session = Annotated[AsyncSession, Depends(session_dependency)]

    def client_key(request: Request, action: str) -> str:
        host = request.client.host if request.client else "unknown"
        return f"{action}:{host}"

    def enforce_rate(request: Request, action: str, limit: int) -> None:
        if not limiter.allow(client_key(request, action), limit):
            raise ServiceError(
                429,
                "rate_limited",
                "Too many requests were sent from this address. Try again in a minute.",
            )

    @router.post("/batches", response_model=BatchRead, status_code=status.HTTP_201_CREATED)
    async def create_batch(payload: BatchCreate, request: Request, session: Session) -> Batch:
        enforce_rate(request, "batch", settings.batch_creations_per_minute)
        if payload.total_cards > settings.max_cards_per_batch:
            raise ServiceError(
                422,
                "too_many_cards",
                f"A batch can contain up to {settings.max_cards_per_batch} cards.",
            )
        batch = Batch(total_cards=payload.total_cards)
        session.add(batch)
        await session.commit()
        await session.refresh(batch)
        return batch

    @router.post(
        "/batches/{batch_id}/cards",
        response_model=LeadRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_card(
        batch_id: UUID,
        request: Request,
        session: Session,
        file: Annotated[UploadFile, File()],
    ) -> Lead:
        enforce_rate(request, "card", settings.card_requests_per_minute)
        content = await file.read(settings.max_file_bytes + 1)
        filename = file.filename or "business-card"
        return await process_card(
            session,
            batch_id=batch_id,
            filename=filename,
            content=content,
            settings=settings,
            extractor=inference_client,
        )

    @router.get("/batches/{batch_id}", response_model=BatchRead)
    async def read_batch(batch_id: UUID, session: Session) -> Batch:
        return await get_batch_or_error(session, batch_id)

    @router.get("/batches/{batch_id}/leads", response_model=list[LeadRead])
    async def list_leads(batch_id: UUID, session: Session) -> list[Lead]:
        await get_batch_or_error(session, batch_id)
        result = await session.scalars(
            select(Lead).where(Lead.batch_id == batch_id).order_by(Lead.created_at, Lead.id)
        )
        return list(result)

    @router.get("/batches/{batch_id}/export.xlsx")
    async def export_leads(
        batch_id: UUID,
        session: Session,
        lead_ids: Annotated[list[UUID] | None, Query()] = None,
    ) -> Response:
        await get_batch_or_error(session, batch_id)
        statement = select(Lead).where(
            Lead.batch_id == batch_id,
            Lead.status.in_([LeadStatus.SUCCESS, LeadStatus.PARTIAL]),
        )
        if lead_ids is not None:
            statement = statement.where(Lead.id.in_(lead_ids))
        result = await session.scalars(statement.order_by(Lead.created_at, Lead.id))
        leads = list(result)
        if not leads:
            raise ServiceError(
                422,
                "no_exportable_leads",
                "Select at least one successfully extracted lead before exporting.",
            )
        payload = build_workbook(leads).getvalue()
        return Response(
            content=payload,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="{export_filename()}"',
                "Cache-Control": "no-store",
            },
        )

    @router.patch("/leads/{lead_id}", response_model=LeadRead)
    async def patch_lead(lead_id: UUID, payload: LeadPatch, session: Session) -> Lead:
        lead = await get_lead_or_error(session, lead_id)
        return await update_lead(session, lead, payload.model_dump(exclude_unset=True))

    @router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_lead(lead_id: UUID, session: Session) -> Response:
        lead = await get_lead_or_error(session, lead_id)
        await session.delete(lead)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
