from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from backend.app.config import Settings
from backend.app.inference import (
    BusinessCardLead,
    InferenceClient,
    InferenceOutputError,
    InferenceServiceError,
    InferenceTimeoutError,
    create_signature,
)
from inference import app as inference_app
from inference.security import SignatureError, verify_signature

VALID_LEAD = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "job_title": "Analytical Engineer",
    "company": "Difference Works",
    "location": "London",
    "phone_number": "+44 20 7946 0000",
    "email": "ada@example.com",
    "confidence": {"email": 0.98},
    "warnings": [],
}


def settings() -> Settings:
    return Settings(
        aws_inference_endpoint="https://model.example/v1/extract",
        aws_inference_shared_secret=SecretStr("test-shared-secret"),
    )


def response(output: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json={"output": output})


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> InferenceClient:
    return InferenceClient(settings(), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_valid_structured_output_is_schema_validated() -> None:
    client = client_for(lambda _request: response(json.dumps(VALID_LEAD)))

    lead = await client.extract(b"image", "image/png")

    assert lead == BusinessCardLead.model_validate(VALID_LEAD)


@pytest.mark.asyncio
async def test_fenced_json_is_accepted_without_accepting_surrounding_prose() -> None:
    output = f"```json\n{json.dumps(VALID_LEAD)}\n```"
    client = client_for(lambda _request: response(output))

    lead = await client.extract(b"image", "image/jpeg")

    assert lead.email == "ada@example.com"


@pytest.mark.asyncio
async def test_missing_fields_become_null_instead_of_being_invented() -> None:
    client = client_for(lambda _request: response('{"first_name":"Prince"}'))

    lead = await client.extract(b"image", "image/webp")

    assert lead.first_name == "Prince"
    assert lead.last_name is None
    assert lead.company is None
    assert lead.email is None


@pytest.mark.asyncio
async def test_malformed_output_gets_one_bounded_repair() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return response("not json")
        body = json.loads(request.content)
        assert body["previous_output"] == "not json"
        assert "Return corrected JSON only" in body["prompt"]
        return response(json.dumps(VALID_LEAD))

    lead = await client_for(handler).extract(b"image", "image/png")

    assert lead.company == "Difference Works"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_malformed_output_stops_after_repair_boundary() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response("still not json")

    with pytest.raises(InferenceOutputError, match="valid structured JSON"):
        await client_for(handler).extract(b"image", "image/png")

    assert attempts == 2


@pytest.mark.asyncio
async def test_timeout_is_retried_once_then_typed() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(InferenceTimeoutError, match="timed out"):
        await client_for(handler).extract(b"image", "image/png")

    assert attempts == 2


@pytest.mark.asyncio
async def test_model_5xx_is_retried_once_then_typed() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response("unavailable", status_code=503)

    with pytest.raises(InferenceServiceError, match="temporarily unavailable"):
        await client_for(handler).extract(b"image", "image/png")

    assert attempts == 2


@pytest.mark.asyncio
async def test_retry_can_recover_from_transient_5xx() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return response("unavailable", status_code=502)
        return response(json.dumps(VALID_LEAD))

    lead = await client_for(handler).extract(b"image", "image/png")

    assert lead.first_name == "Ada"
    assert attempts == 2


@pytest.mark.asyncio
async def test_request_is_signed_and_contains_no_arbitrary_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response(json.dumps(VALID_LEAD))

    await client_for(handler).extract(b"secret image bytes", "image/png")

    request = captured[0]
    body = json.loads(request.content)
    assert request.url == "https://model.example/v1/extract"
    assert request.headers["x-o-hive-timestamp"]
    assert request.headers["x-o-hive-signature"].startswith("sha256=")
    assert base64.b64decode(body["image_base64"]) == b"secret image bytes"
    assert "ONLY information visible" in body["prompt"]


def test_signature_contract_matches_runtime_verifier() -> None:
    body = b'{"a":1}'
    timestamp = "1760000000"
    signature = create_signature("shared", timestamp, body)

    verify_signature(
        secret="shared",  # noqa: S106 - deterministic non-production test fixture
        timestamp=timestamp,
        signature=signature,
        body=body,
        now=1760000001,
    )


def test_invalid_or_stale_signature_is_rejected() -> None:
    body = b"payload"
    valid = "sha256=" + hmac.new(
        b"shared",
        b"1760000000." + hashlib.sha256(body).hexdigest().encode(),
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(SignatureError, match="expired"):
        verify_signature("shared", "1760000000", valid, body, now=1760000400)
    with pytest.raises(SignatureError, match="invalid"):
        verify_signature("shared", "1760000000", "sha256=bad", body, now=1760000001)


def test_inference_secret_can_be_loaded_from_read_only_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / "inference-secret"
    secret_file.write_text("from-mounted-secret\n", encoding="utf-8")
    monkeypatch.setenv("INFERENCE_SHARED_SECRET_FILE", str(secret_file))
    monkeypatch.setenv("INFERENCE_SHARED_SECRET", "ignored-environment-value")

    assert inference_app._shared_secret() == "from-mounted-secret"
