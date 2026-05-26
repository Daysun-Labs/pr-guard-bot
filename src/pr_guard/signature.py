"""GitHub webhook signature verification (X-Hub-Signature-256, HMAC-SHA256)."""
from __future__ import annotations

import hashlib
import hmac


class InvalidSignature(ValueError):
    """Raised when an X-Hub-Signature-256 header fails verification."""


def compute_signature(secret: str | bytes, body: bytes) -> str:
    """Compute the expected X-Hub-Signature-256 value for `body` under `secret`."""
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("body must be bytes")
    mac = hmac.new(secret, msg=bytes(body), digestmod=hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(secret: str | bytes, body: bytes, header: str | None) -> bool:
    """Constant-time check that `header` matches HMAC-SHA256(body, secret).

    Expects header form `sha256=<hexdigest>`. Returns True on match, False otherwise.
    Never raises on malformed input — returns False.
    """
    if not header or not isinstance(header, str):
        return False
    if not header.startswith("sha256="):
        return False
    if not isinstance(body, (bytes, bytearray)):
        return False
    try:
        expected = compute_signature(secret, bytes(body))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, header)


def require_signature(secret: str | bytes, body: bytes, header: str | None) -> None:
    """Raise InvalidSignature if `header` does not verify against `body`."""
    if not verify_signature(secret, body, header):
        raise InvalidSignature("X-Hub-Signature-256 verification failed")
