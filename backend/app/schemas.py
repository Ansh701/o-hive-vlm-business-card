from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models import BatchStatus, LeadStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchCreate(StrictModel):
    total_cards: int = Field(ge=1, le=50)


class BatchRead(StrictModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    status: BatchStatus
    total_cards: int
    processed_cards: int
    successful_cards: int
    failed_cards: int
    created_at: datetime
    completed_at: datetime | None


class LeadFields(StrictModel):
    first_name: str | None = Field(default=None, max_length=200)
    last_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=500)
    phone_number: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)

    @field_validator(
        "first_name",
        "last_name",
        "job_title",
        "company",
        "location",
        "phone_number",
        "email",
    )
    @classmethod
    def trim_blank_values(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class LeadPatch(LeadFields):
    pass


class LeadRead(LeadFields):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    batch_id: UUID
    source_filename: str
    status: LeadStatus
    warnings: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ErrorResponse(StrictModel):
    detail: str
    code: str
