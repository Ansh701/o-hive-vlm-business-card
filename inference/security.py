from __future__ import annotations

import hashlib
import hmac


class SignatureError(ValueError):
    pass


def verify_signature(
    secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    *,
    now: int,
    tolerance_seconds: int = 300,
) -> None:
    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise SignatureError("invalid request timestamp") from exc
    if abs(now - signed_at) > tolerance_seconds:
        raise SignatureError("request signature expired")

    body_digest = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}.{body_digest}".encode()
    expected = "sha256=" + hmac.new(
        secret.encode(), message, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("invalid request signature")

