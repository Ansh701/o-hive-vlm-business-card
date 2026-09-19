from __future__ import annotations

import json
from collections import deque
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings
from backend.app.inference import BusinessCardLead, InferenceServiceError
from backend.app.main import create_app
from backend.app.models import Batch, BatchStatus, Lead, LeadStatus


def png_bytes(color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (640, 360), color).save(buffer, format="PNG")
    return buffer.getvalue()


class StubInference:
    def __init__(self, *outcomes: BusinessCardLead | Exception) -> None:
        self.outcomes = deque(outcomes)
        self.calls = 0

    async def extract(self, image: bytes, media_type: str) -> BusinessCardLead:
        self.calls += 1
        assert image
        assert media_type in {"image/jpeg", "image/png", "image/webp"}
        outcome = self.outcomes.popleft() if self.outcomes else BusinessCardLead()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def extracted(**changes: Any) -> BusinessCardLead:
    values: dict[str, Any] = {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "job_title": "Engineer",
        "company": "Difference Works",
        "location": "London",
        "phone_number": "+44 20 7946 0000",
        "email": "ADA@EXAMPLE.COM",
        "confidence": {"email": 0.97},
        "warnings": [],
    }
    values.update(changes)
    return BusinessCardLead.model_validate(values)


async def make_client(
    session_factory: async_sessionmaker[AsyncSession],
    inference: StubInference,
    **setting_overrides: Any,
) -> tuple[httpx.AsyncClient, Any]:
    settings = Settings(environment="test", **setting_overrides)
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        inference_client=inference,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )
    return client, app


@pytest.mark.asyncio
async def test_health_and_readiness_are_separate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference())
    async with client:
        health = await client.get("/health")
        ready = await client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "alive"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "database": "ok"}


@pytest.mark.asyncio
async def test_create_batch_enforces_configured_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(
        session_factory, StubInference(), max_cards_per_batch=2
    )
    async with client:
        accepted = await client.post("/api/batches", json={"total_cards": 2})
        rejected = await client.post("/api/batches", json={"total_cards": 3})

    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["status"] == "UPLOADED"
    assert rejected.status_code == 422
    assert "up to 2" in rejected.json()["detail"]


@pytest.mark.asyncio
async def test_multiple_images_persist_normalized_leads_and_complete_batch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(extracted(), extracted(first_name="Grace", email=None))
    client, _app = await make_client(session_factory, inference)
    async with client:
        created = await client.post("/api/batches", json={"total_cards": 2})
        batch_id = created.json()["id"]
        first = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("ada.png", png_bytes("white"), "image/png")},
        )
        second = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("grace.png", png_bytes("navy"), "image/png")},
        )
        batch = await client.get(f"/api/batches/{batch_id}")
        leads = await client.get(f"/api/batches/{batch_id}/leads")

    assert first.status_code == 201
    assert first.json()["email"] == "ADA@example.com"
    assert second.status_code == 201
    assert batch.json()["status"] == "COMPLETED"
    assert batch.json()["processed_cards"] == 2
    assert [lead["first_name"] for lead in leads.json()] == ["Ada", "Grace"]
    assert inference.calls == 2


@pytest.mark.asyncio
async def test_duplicate_image_is_rejected_without_second_inference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(extracted())
    client, _app = await make_client(session_factory, inference)
    card = png_bytes()
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 2})).json()["id"]
        first = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("one.png", card, "image/png")},
        )
        duplicate = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("../../two.png", card, "image/png")},
        )
        batch = await client.get(f"/api/batches/{batch_id}")

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate_card"
    assert batch.json()["status"] == "PARTIAL_SUCCESS"
    assert batch.json()["processed_cards"] == 2
    assert batch.json()["successful_cards"] == 1
    assert batch.json()["failed_cards"] == 1
    assert inference.calls == 1


@pytest.mark.asyncio
async def test_invalid_image_is_recorded_as_failed_without_calling_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference()
    client, _app = await make_client(session_factory, inference)
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        invalid = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("../../attack.jpg", b"<html>bad</html>", "image/jpeg")},
        )
        batch = await client.get(f"/api/batches/{batch_id}")
        leads = await client.get(f"/api/batches/{batch_id}/leads")

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_image"
    assert batch.json()["status"] == "FAILED"
    assert leads.json()[0]["source_filename"] == "attack.jpg"
    assert leads.json()[0]["status"] == "FAILED"
    assert inference.calls == 0


@pytest.mark.asyncio
async def test_model_failure_produces_partial_success_and_keeps_good_lead(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(
        extracted(), InferenceServiceError("The AWS model is temporarily unavailable.")
    )
    client, _app = await make_client(session_factory, inference)
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 2})).json()["id"]
        good = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("good.png", png_bytes("white"), "image/png")},
        )
        failed = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("hard.png", png_bytes("gray"), "image/png")},
        )
        batch = await client.get(f"/api/batches/{batch_id}")
        leads = await client.get(f"/api/batches/{batch_id}/leads")

    assert good.json()["status"] == "SUCCESS"
    assert failed.status_code == 201
    assert failed.json()["status"] == "FAILED"
    assert "temporarily unavailable" in failed.json()["error_message"]
    assert batch.json()["status"] == "PARTIAL_SUCCESS"
    assert len(leads.json()) == 2


@pytest.mark.asyncio
async def test_low_confidence_and_ambiguous_phone_need_review(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(
        extracted(phone_number="(332) 241 6313", confidence={"email": 0.4})
    )
    client, _app = await make_client(session_factory, inference)
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        result = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("review.png", png_bytes(), "image/png")},
        )

    assert result.json()["status"] == "PARTIAL"
    assert "Phone country is ambiguous" in " ".join(result.json()["warnings"])
    assert "Low confidence: email" in result.json()["warnings"]


@pytest.mark.asyncio
async def test_lead_can_be_edited_with_allowlisted_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference(extracted()))
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        lead = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("card.png", png_bytes(), "image/png")},
        )
        lead_id = lead.json()["id"]
        updated = await client.patch(
            f"/api/leads/{lead_id}",
            json={"first_name": "  Augusta Ada  ", "email": "ADA@NEW.EXAMPLE"},
        )
        invalid = await client.patch(
            f"/api/leads/{lead_id}", json={"email": "not an email"}
        )
        unknown = await client.patch(
            f"/api/leads/{lead_id}", json={"is_admin": True}
        )

    assert updated.status_code == 200
    assert updated.json()["first_name"] == "Augusta Ada"
    assert updated.json()["email"] == "ADA@new.example"
    assert invalid.status_code == 422
    assert unknown.status_code == 422


@pytest.mark.asyncio
async def test_lead_can_be_removed_and_missing_resources_are_404(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference(extracted()))
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        lead_id = (
            await client.post(
                f"/api/batches/{batch_id}/cards",
                files={"file": ("card.png", png_bytes(), "image/png")},
            )
        ).json()["id"]
        removed = await client.delete(f"/api/leads/{lead_id}")
        missing_lead = await client.patch(
            f"/api/leads/{uuid4()}", json={"first_name": "Nobody"}
        )
        missing_batch = await client.get(f"/api/batches/{uuid4()}")
        listed = await client.get(f"/api/batches/{batch_id}/leads")

    assert removed.status_code == 204
    assert missing_lead.status_code == 404
    assert missing_batch.status_code == 404
    assert listed.json() == []


@pytest.mark.asyncio
async def test_batch_creation_rate_limit_returns_clear_429(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(
        session_factory, StubInference(), batch_creations_per_minute=1
    )
    async with client:
        first = await client.post("/api/batches", json={"total_cards": 1})
        limited = await client.post("/api/batches", json={"total_cards": 1})

    assert first.status_code == 201
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert "Try again" in limited.json()["detail"]


@pytest.mark.asyncio
async def test_card_rate_limit_blocks_rapid_paid_requests(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(extracted(), extracted())
    client, _app = await make_client(
        session_factory, inference, card_requests_per_minute=1
    )
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 2})).json()["id"]
        first = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("one.png", png_bytes("white"), "image/png")},
        )
        limited = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("two.png", png_bytes("black"), "image/png")},
        )

    assert first.status_code == 201
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert inference.calls == 1


@pytest.mark.asyncio
async def test_declared_oversized_request_is_rejected_before_processing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(extracted())
    client, _app = await make_client(session_factory, inference, max_file_bytes=1024)
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        rejected = await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("one.png", png_bytes(), "image/png")},
            headers={"Content-Length": str(2 * 1024 * 1024)},
        )

    assert rejected.status_code == 413
    assert rejected.json()["code"] == "request_too_large"
    assert inference.calls == 0


@pytest.mark.asyncio
async def test_malformed_identifier_and_huge_edit_are_safe_validation_errors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference(extracted()))
    async with client:
        malformed = await client.get("/api/batches/not-a-uuid")
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        lead_id = (
            await client.post(
                f"/api/batches/{batch_id}/cards",
                files={"file": ("one.png", png_bytes(), "image/png")},
            )
        ).json()["id"]
        huge = await client.patch(
            f"/api/leads/{lead_id}", json={"first_name": "x" * 201}
        )

    assert malformed.status_code == 422
    assert malformed.json()["code"] == "validation_error"
    assert huge.status_code == 422
    assert huge.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_daily_card_cap_stops_paid_inference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inference = StubInference(extracted(), extracted())
    client, _app = await make_client(session_factory, inference, max_daily_cards=1)
    async with client:
        first_batch = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        await client.post(
            f"/api/batches/{first_batch}/cards",
            files={"file": ("one.png", png_bytes("white"), "image/png")},
        )
        second_batch = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        capped = await client.post(
            f"/api/batches/{second_batch}/cards",
            files={"file": ("two.png", png_bytes("black"), "image/png")},
        )

    assert capped.status_code == 429
    assert capped.json()["code"] == "daily_card_limit"
    assert inference.calls == 1


@pytest.mark.asyncio
async def test_security_headers_are_present_on_html_and_api_responses(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference())
    async with client:
        response = await client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_database_contains_persisted_lead_after_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, _app = await make_client(session_factory, StubInference(extracted()))
    async with client:
        batch_id = (await client.post("/api/batches", json={"total_cards": 1})).json()["id"]
        await client.post(
            f"/api/batches/{batch_id}/cards",
            files={"file": ("persist.png", png_bytes(), "image/png")},
        )

    async with session_factory() as session:
        persisted_batch_id = UUID(batch_id)
        batch = await session.get(Batch, persisted_batch_id)
        lead = await session.scalar(select(Lead).where(Lead.batch_id == persisted_batch_id))

    assert batch is not None and batch.status is BatchStatus.COMPLETED
    assert lead is not None and lead.status is LeadStatus.SUCCESS
    assert lead.content_sha256
    assert lead.email == "ADA@example.com"


def test_api_error_response_is_json_not_stack_trace() -> None:
    payload = json.dumps({"detail": "safe", "code": "example"})
    assert "Traceback" not in payload
