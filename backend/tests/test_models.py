from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.models import Batch, BatchStatus, Lead, LeadStatus
from backend.app.schemas import BatchCreate, LeadPatch


def assert_batch_status(batch: Batch, expected: BatchStatus) -> None:
    assert batch.status is expected


def test_settings_rejects_unsafe_upload_limits() -> None:
    with pytest.raises(ValidationError):
        Settings(max_cards_per_batch=0)

    with pytest.raises(ValidationError):
        Settings(max_file_bytes=100)


def test_settings_default_to_safe_local_values() -> None:
    settings = Settings()

    assert settings.max_cards_per_batch == 20
    assert settings.max_file_bytes == 4 * 1024 * 1024
    assert settings.max_total_bytes == 64 * 1024 * 1024
    assert settings.max_image_pixels == 24_000_000
    assert settings.min_image_short_side == 100
    assert settings.min_image_long_side == 160
    assert settings.inference_concurrency == 2
    assert settings.environment == "development"


def test_render_postgres_url_is_normalized_to_asyncpg() -> None:
    settings = Settings(database_url="postgresql://user:password@database.example/o_hive")

    assert settings.database_url == (
        "postgresql+asyncpg://user:password@database.example/o_hive"
    )


def test_batch_and_lead_use_uuid_identifiers_and_nullable_fields() -> None:
    batch = Batch(total_cards=2)
    lead = Lead(
        batch_id=batch.id,
        source_filename="card.png",
        content_sha256="a" * 64,
    )

    assert isinstance(batch.id, UUID)
    assert isinstance(lead.id, UUID)
    assert batch.status is BatchStatus.UPLOADED
    assert lead.status is LeadStatus.QUEUED
    assert lead.email is None
    assert lead.first_name is None


def test_batch_terminal_status_is_derived_from_card_outcomes() -> None:
    batch = Batch(total_cards=3)

    batch.record_result(LeadStatus.SUCCESS)
    assert_batch_status(batch, BatchStatus.PROCESSING)
    batch.record_result(LeadStatus.PARTIAL)
    assert_batch_status(batch, BatchStatus.PROCESSING)
    batch.record_result(LeadStatus.FAILED)

    assert_batch_status(batch, BatchStatus.PARTIAL_SUCCESS)
    assert batch.processed_cards == 3
    assert batch.successful_cards == 2
    assert batch.failed_cards == 1
    assert isinstance(batch.completed_at, datetime)
    assert batch.completed_at.tzinfo is UTC


def test_batch_create_and_lead_patch_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        BatchCreate.model_validate({"total_cards": 2, "admin": True})

    with pytest.raises(ValidationError):
        LeadPatch.model_validate({"email": "a@example.com", "is_admin": True})


def test_lead_patch_allows_missing_official_fields_but_bounds_text() -> None:
    patch = LeadPatch(email=None, first_name="Ada")

    assert patch.email is None
    assert patch.first_name == "Ada"

    with pytest.raises(ValidationError):
        LeadPatch(first_name="x" * 201)


def test_batch_create_enforces_configured_product_boundary() -> None:
    assert BatchCreate(total_cards=1).total_cards == 1
    with pytest.raises(ValidationError):
        BatchCreate(total_cards=0)
    with pytest.raises(ValidationError):
        BatchCreate(total_cards=51)


def test_model_ids_can_be_supplied_for_database_hydration() -> None:
    batch_id = uuid4()
    lead_id = uuid4()
    batch = Batch(id=batch_id, total_cards=1)
    lead = Lead(
        id=lead_id,
        batch_id=batch_id,
        source_filename="safe.webp",
        content_sha256="b" * 64,
    )

    assert batch.id == batch_id
    assert lead.id == lead_id
