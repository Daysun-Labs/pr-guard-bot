"""Slack incoming-webhook HTTP sender.

Side-effectful counterpart to slack_format. Accepts an injectable HTTP client
(default: httpx.Client) so tests can mock transport without network I/O.
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx


class SlackWebhookError(RuntimeError):
    """Raised when Slack webhook delivery fails (non-2xx or transport error)."""


class _HttpClient(Protocol):
    def post(self, url: str, json: dict[str, Any]) -> Any: ...


def send_slack_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    client: _HttpClient | None = None,
    timeout: float = 10.0,
) -> int:
    """POST `payload` as JSON to Slack `webhook_url`.

    Returns the HTTP status code on success (2xx).
    Raises SlackWebhookError on non-2xx response or network/transport failure.
    """
    if not webhook_url:
        raise SlackWebhookError("webhook_url is empty")

    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=timeout)
    try:
        try:
            resp = http.post(webhook_url, json=payload)
        except httpx.HTTPError as exc:
            raise SlackWebhookError(f"transport error: {exc}") from exc

        status = getattr(resp, "status_code", None)
        if status is None or not (200 <= status < 300):
            body = getattr(resp, "text", "")
            raise SlackWebhookError(f"slack webhook returned {status}: {body!r}")
        return status
    finally:
        if owns_client and hasattr(http, "close"):
            http.close()
