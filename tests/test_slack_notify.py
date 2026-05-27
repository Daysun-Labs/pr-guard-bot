"""Unit tests for send_slack_webhook using a mock HTTP client."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from pr_guard.slack_notify import SlackWebhookError, send_slack_webhook


class _MockResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _MockClient:
    def __init__(self, response: _MockResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any]) -> _MockResponse:
        self.calls.append((url, json))
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def test_send_success_200() -> None:
    client = _MockClient(response=_MockResponse(200, "ok"))
    status = send_slack_webhook(
        "https://example.invalid/slack-webhook/AAA/BBB/CCC",
        {"text": "hi"},
        client=client,
    )
    assert status == 200
    assert len(client.calls) == 1
    url, body = client.calls[0]
    assert url.endswith("/CCC")
    assert body == {"text": "hi"}


def test_send_success_204() -> None:
    client = _MockClient(response=_MockResponse(204))
    assert send_slack_webhook("https://x", {"a": 1}, client=client) == 204


def test_send_failure_non_2xx() -> None:
    client = _MockClient(response=_MockResponse(500, "boom"))
    with pytest.raises(SlackWebhookError) as ei:
        send_slack_webhook("https://x", {"a": 1}, client=client)
    assert "500" in str(ei.value)


def test_send_failure_4xx() -> None:
    client = _MockClient(response=_MockResponse(404, "no_such_hook"))
    with pytest.raises(SlackWebhookError):
        send_slack_webhook("https://x", {"a": 1}, client=client)


def test_send_failure_network_error() -> None:
    client = _MockClient(exc=httpx.ConnectError("dns fail"))
    with pytest.raises(SlackWebhookError) as ei:
        send_slack_webhook("https://x", {"a": 1}, client=client)
    assert "transport error" in str(ei.value)


def test_send_failure_timeout() -> None:
    client = _MockClient(exc=httpx.ReadTimeout("slow"))
    with pytest.raises(SlackWebhookError):
        send_slack_webhook("https://x", {"a": 1}, client=client)


def test_empty_webhook_url() -> None:
    with pytest.raises(SlackWebhookError):
        send_slack_webhook("", {"a": 1}, client=_MockClient(response=_MockResponse(200)))
