"""Sub-AC 4: end-to-end latency integration test.

Injects a GitHub `pull_request` webhook payload and drives it through the
real pipeline (parse → format → Slack notify) using an in-process fake HTTP
transport. Asserts that the total wall-clock elapsed time from PR event
injection to Slack delivery is well under the 5-minute (300s) budget defined
by SEED/PRD for the MVP shipping cycle.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from pr_guard.slack_format import format_pr_event_for_slack
from pr_guard.slack_notify import SlackWebhookError, send_slack_webhook
from pr_guard.webhook import parse_pr_webhook


FIVE_MINUTES_SECONDS = 300.0


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class _FakeSlackClient:
    """In-process Slack webhook transport — records calls, returns 200."""

    def __init__(self, simulated_latency_s: float = 0.0) -> None:
        self.simulated_latency_s = simulated_latency_s
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        if self.simulated_latency_s:
            time.sleep(self.simulated_latency_s)
        self.calls.append((url, json))
        return _FakeResponse(200, "ok")


def _sample_pr_payload(pr_number: int = 42) -> dict[str, Any]:
    return {
        "action": "opened",
        "pull_request": {
            "number": pr_number,
            "diff_url": f"https://github.com/o/r/pull/{pr_number}.diff",
            "html_url": f"https://github.com/o/r/pull/{pr_number}",
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "user": {"login": "darbykim"},
        },
        "repository": {"full_name": "o/r"},
    }


def _run_pipeline(
    payload: dict[str, Any],
    *,
    webhook_url: str,
    client: _FakeSlackClient,
) -> tuple[float, dict[str, Any]]:
    """Execute the full event→Slack pipeline and return (elapsed_seconds, slack_payload)."""
    start = time.monotonic()
    event = parse_pr_webhook(payload, event_type="pull_request")
    slack_payload = format_pr_event_for_slack(event)
    status = send_slack_webhook(webhook_url, slack_payload, client=client)
    elapsed = time.monotonic() - start
    assert status == 200
    return elapsed, slack_payload


def test_e2e_latency_under_five_minutes() -> None:
    """Pipeline completes well under the 5-minute SEED budget."""
    client = _FakeSlackClient()
    elapsed, slack_payload = _run_pipeline(
        _sample_pr_payload(),
        webhook_url="https://hooks.slack.test/T/B/X",
        client=client,
    )

    assert elapsed < FIVE_MINUTES_SECONDS, (
        f"e2e latency {elapsed:.3f}s exceeded 5-min budget"
    )
    # Sanity: typical in-process run is sub-second; guard against accidental
    # blocking I/O sneaking into the pipeline.
    assert elapsed < 5.0, f"in-process pipeline unexpectedly slow: {elapsed:.3f}s"
    assert len(client.calls) == 1
    assert client.calls[0][1] == slack_payload
    assert "PR #42 opened by darbykim" in slack_payload["text"]


def test_e2e_latency_budget_with_simulated_network_delay() -> None:
    """Even with a simulated slow Slack call, pipeline stays under budget."""
    client = _FakeSlackClient(simulated_latency_s=0.05)
    elapsed, _ = _run_pipeline(
        _sample_pr_payload(pr_number=7),
        webhook_url="https://hooks.slack.test/T/B/X",
        client=client,
    )
    assert 0.05 <= elapsed < FIVE_MINUTES_SECONDS


def test_e2e_latency_budget_is_five_minutes() -> None:
    """Lock the SEED-defined latency budget to 5 minutes (300s)."""
    assert FIVE_MINUTES_SECONDS == 300.0


def test_e2e_slack_failure_is_surfaced_within_budget() -> None:
    """A Slack 5xx failure is raised quickly (no silent multi-minute hangs)."""

    class _FailingClient:
        def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
            return _FakeResponse(500, "boom")

    start = time.monotonic()
    with pytest.raises(SlackWebhookError):
        send_slack_webhook(
            "https://hooks.slack.test/T/B/X",
            format_pr_event_for_slack(
                parse_pr_webhook(_sample_pr_payload(), event_type="pull_request")
            ),
            client=_FailingClient(),
        )
    elapsed = time.monotonic() - start
    assert elapsed < FIVE_MINUTES_SECONDS
