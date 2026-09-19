from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utc_now() -> datetime:
    return datetime.now(UTC)


class BatchStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LeadStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[object, object]] = {
        list[str]: JSON().with_variant(JSONB(), "postgresql")
    }


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status", native_enum=False),
        default=BatchStatus.UPLOADED,
        index=True,
    )
    total_cards: Mapped[int] = mapped_column(Integer)
    processed_cards: Mapped[int] = mapped_column(Integer, default=0)
    successful_cards: Mapped[int] = mapped_column(Integer, default=0)
    failed_cards: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    leads: Mapped[list[Lead]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", passive_deletes=True
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("status", BatchStatus.UPLOADED)
        kwargs.setdefault("processed_cards", 0)
        kwargs.setdefault("successful_cards", 0)
        kwargs.setdefault("failed_cards", 0)
        kwargs.setdefault("created_at", utc_now())
        super().__init__(**kwargs)

    def record_result(self, status: LeadStatus) -> None:
        self.status = BatchStatus.PROCESSING
        self.processed_cards += 1
        if status in {LeadStatus.SUCCESS, LeadStatus.PARTIAL}:
            self.successful_cards += 1
        else:
            self.failed_cards += 1

        if self.processed_cards < self.total_cards:
            return

        self.completed_at = utc_now()
        if self.successful_cards == self.total_cards:
            self.status = BatchStatus.COMPLETED
        elif self.successful_cards:
            self.status = BatchStatus.PARTIAL_SUCCESS
        else:
            self.status = BatchStatus.FAILED


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("batch_id", "content_sha256", name="uq_leads_batch_hash"),
        Index("ix_leads_batch_created", "batch_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    source_filename: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(200), default=None)
    last_name: Mapped[str | None] = mapped_column(String(200), default=None)
    job_title: Mapped[str | None] = mapped_column(String(300), default=None)
    company: Mapped[str | None] = mapped_column(String(300), default=None)
    location: Mapped[str | None] = mapped_column(String(500), default=None)
    phone_number: Mapped[str | None] = mapped_column(String(100), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", native_enum=False),
        default=LeadStatus.QUEUED,
        index=True,
    )
    warnings: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql")),
        default=list,
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batch: Mapped[Batch] = relationship(back_populates="leads")

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("status", LeadStatus.QUEUED)
        kwargs.setdefault("warnings", [])
        kwargs.setdefault("created_at", utc_now())
        kwargs.setdefault("updated_at", utc_now())
        super().__init__(**kwargs)
