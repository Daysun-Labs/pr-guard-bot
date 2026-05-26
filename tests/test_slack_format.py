"""Unit tests for slack_format.format_pr_event_for_slack."""
from __future__ import annotations

from pr_guard.slack_format import format_pr_event_for_slack
from pr_guard.webhook import NormalizedPREvent


def _event(**overrides) -> NormalizedPREvent:
    base = dict(
        action="opened",
        pr_number=42,
        repo_full_name="darbykim/pr-guard",
        author="darbykim",
        head_branch="feat/x",
        base_branch="main",
        diff_url="https://github.com/darbykim/pr-guard/pull/42.diff",
        html_url="https://github.com/darbykim/pr-guard/pull/42",
    )
    base.update(overrides)
    return NormalizedPREvent(**base)


def test_returns_expected_structure():
    payload = format_pr_event_for_slack(_event())
    assert isinstance(payload, dict)
    assert set(payload.keys()) == {"text", "blocks"}
    assert payload["text"] == "[darbykim/pr-guard] PR #42 opened by darbykim"

    blocks = payload["blocks"]
    assert isinstance(blocks, list) and len(blocks) == 2

    section, context = blocks
    assert section["type"] == "section"
    assert section["text"]["type"] == "mrkdwn"
    assert "PR #42" in section["text"]["text"]
    assert section["text"]["text"].startswith("*") and section["text"]["text"].endswith("*")

    assert context["type"] == "context"
    elements = context["elements"]
    assert isinstance(elements, list) and len(elements) == 1
    text = elements[0]["text"]
    assert "feat/x → main" in text
    assert "https://github.com/darbykim/pr-guard/pull/42" in text
    assert ".diff" in text


def test_action_verb_mapping():
    assert "updated by" in format_pr_event_for_slack(_event(action="synchronize"))["text"]
    assert "marked ready for review by" in format_pr_event_for_slack(
        _event(action="ready_for_review")
    )["text"]
    assert "closed by" in format_pr_event_for_slack(_event(action="closed"))["text"]
    assert "opened by" in format_pr_event_for_slack(_event(action="opened"))["text"]


def test_pure_deterministic():
    e = _event()
    assert format_pr_event_for_slack(e) == format_pr_event_for_slack(e)
