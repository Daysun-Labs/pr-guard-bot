from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from pr_guard_adapter.core import (
    AdapterConfig,
    ForbiddenRequest,
    InMemoryIdempotencyCache,
    ProposalService,
)
from pr_guard_adapter.models import ReviewRequest


class FakeHermesClient:
    def __init__(self, *outputs: object) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, str]]] = []

    def complete_json(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if not self.outputs:
            raise AssertionError("unexpected Hermes call")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return str(output)


BASE_PAYLOAD = {
    "schema_version": "pr-guard.hermes-proposal/v1",
    "task": "code_fix",
    "metadata": {
        "repo": "Daysun-Labs/astate-brain",
        "pr_number": 42,
        "base_ref": "main",
        "head_ref": "feature/prd-drift",
        "head_sha": "abc123",
    },
    "drift": {
        "type": "missing_requirement",
        "severity": "high",
        "source": "prd",
        "source_file": "PRD.md",
        "section": "Acceptance",
        "kind": "acceptance",
        "quote": "The PR must explain the new Hermes adapter rollout plan.",
        "line": 34,
        "score": 0.42,
    },
    "repo_context": "README.md\nsrc/pr_guard/main.py\n",
    "output_path": "docs/pr-guard-proposals/hermes-adapter-rollout.md",
    "proposal_shape": ["action", "new_content", "message", "rationale"],
}

BLOCKING_PAYLOAD = {
    "schema_version": "pr-guard.blocking-drift/v1",
    "task": "blocking_drift_classification",
    "metadata": BASE_PAYLOAD["metadata"],
    "advisory_drifts": [BASE_PAYLOAD["drift"]],
    "diff_summary": (
        "FILE src/webhook_handler.py (modified, +12, -3)\n"
        "symbols: process_webhook\n"
        "added:\n"
        "def process_webhook(payload):\n"
        "    return handle_payload(payload)"
    ),
    "decision_shape": {
        "blocking": [
            {
                "index": 0,
                "reason": "why this scoped advisory finding is real blocking drift",
            }
        ]
    },
}

REVIEW_PAYLOAD = {
    "schema_version": "pr-guard.review/v1",
    "task": "review",
    "metadata": BASE_PAYLOAD["metadata"],
    "diff_summary": (
        "FILE adapter/pr_guard_adapter/core.py (modified, +30, -0)\n"
        "symbols: ProposalService.handle\n"
        "added:\n"
        "if payload.get('task') == 'review':\n"
        "    return self._handle_review(payload)"
    ),
    "repo_context": "adapter/pr_guard_adapter/core.py\nadapter/pr_guard_adapter/models.py\n",
    "report_shape": {
        "score": 0,
        "summary": "short review summary",
        "findings": [
            {
                "category": "bug",
                "severity": "warn",
                "file": "path",
                "line": 1,
                "quote": "short quote",
                "suggestion": "short suggestion",
            }
        ],
    },
}


def config() -> AdapterConfig:
    return AdapterConfig(
        allowed_repos={"Daysun-Labs/astate-brain"},
        single_repo_mode=None,
        hermes_api_url="http://127.0.0.1:8642",
        hermes_api_key="test-key",
        model="hermes-pr-guard-test",
    )


def test_code_fix_request_returns_validated_update_and_strict_prompt() -> None:
    hermes = FakeHermesClient(
        json.dumps(
            {
                "action": "update",
                "new_content": (
                    "# Proposal\n\n"
                    "## Missing requirement\n"
                    "The PR must explain the new Hermes adapter rollout plan.\n\n"
                    "## Why it matters\n"
                    "Reviewers need bounded rollout evidence.\n\n"
                    "## Proposed approach\n"
                    "Add docs.\n\n"
                    "## Validation idea\n"
                    "Run pr-guard."
                ),
                "message": "docs: propose Hermes adapter rollout",
                "rationale": "Creates review material without mutating source code.",
            }
        )
    )
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(BASE_PAYLOAD)

    assert result["action"] == "update"
    assert result["new_content"].startswith("# Proposal")
    assert result["message"] == "docs: propose Hermes adapter rollout"
    assert len(hermes.calls) == 1
    system_prompt = hermes.calls[0][0]["content"]
    user_prompt = hermes.calls[0][1]["content"]
    assert "Return JSON only" in system_prompt
    assert "code_fix" in user_prompt
    assert "Daysun-Labs/astate-brain" in user_prompt


def test_repo_allowlist_blocks_unapproved_repo_before_hermes_call() -> None:
    payload = BASE_PAYLOAD | {"metadata": BASE_PAYLOAD["metadata"] | {"repo": "evil/repo"}}
    hermes = FakeHermesClient('{"action":"skip","reason":"should not be called"}')
    service = ProposalService(config(), hermes_client=hermes)

    with pytest.raises(ForbiddenRequest):
        service.handle(payload)

    assert hermes.calls == []


def test_timeout_becomes_skip_not_exception() -> None:
    hermes = FakeHermesClient(httpx.TimeoutException("slow"))
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(BASE_PAYLOAD)

    assert result == {
        "action": "skip",
        "reason": "Hermes proposal timed out; leaving drift for human review.",
    }


def test_malformed_hermes_output_becomes_skip() -> None:
    hermes = FakeHermesClient("I would update the docs, but here is prose instead.")
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(BASE_PAYLOAD)

    assert result["action"] == "skip"
    assert "malformed" in result["reason"].lower()


def test_idempotency_cache_reuses_first_result() -> None:
    hermes = FakeHermesClient(
        '{"action":"skip","reason":"first result"}',
        '{"action":"skip","reason":"second result"}',
    )
    service = ProposalService(
        config(),
        hermes_client=hermes,
        cache=InMemoryIdempotencyCache(),
    )

    first = service.handle(BASE_PAYLOAD)
    second = service.handle(BASE_PAYLOAD)

    assert first == second == {"action": "skip", "reason": "first result"}
    assert len(hermes.calls) == 1


def test_blocking_classification_returns_validated_indexes_and_prompt() -> None:
    hermes = FakeHermesClient(
        json.dumps(
            {
                "blocking": [
                    {
                        "index": 0,
                        "reason": "Webhook handler changed but verification remains absent.",
                    },
                    {"index": 99, "reason": "out of range"},
                ]
            }
        )
    )
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(BLOCKING_PAYLOAD)

    assert result == {
        "blocking": [
            {
                "index": 0,
                "reason": "Webhook handler changed but verification remains absent.",
            }
        ]
    }
    assert len(hermes.calls) == 1
    assert "semantic blocking classifier" in hermes.calls[0][0]["content"]
    assert "blocking_drift_classification" in hermes.calls[0][1]["content"]


def test_blocking_classification_malformed_or_timeout_degrades_to_empty() -> None:
    malformed = ProposalService(config(), hermes_client=FakeHermesClient("not json"))
    timed_out = ProposalService(config(), hermes_client=FakeHermesClient(httpx.TimeoutException("slow")))

    assert malformed.handle(BLOCKING_PAYLOAD) == {"blocking": []}
    assert timed_out.handle(BLOCKING_PAYLOAD) == {"blocking": []}


def test_blocking_classification_empty_advisory_skips_hermes_call() -> None:
    hermes = FakeHermesClient('{"blocking":[{"index":0}]}')
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(BLOCKING_PAYLOAD | {"advisory_drifts": []})

    assert result == {"blocking": []}
    assert hermes.calls == []


def test_review_request_returns_report_and_prompt() -> None:
    report = {
        "score": 2,
        "summary": "Review found one quality issue.",
        "findings": [
            {
                "category": "quality",
                "severity": "warn",
                "file": "adapter/pr_guard_adapter/core.py",
                "line": 123,
                "quote": "return self._handle_review(payload)",
                "suggestion": "Pass request_id through the review handler.",
            }
        ],
    }
    hermes = FakeHermesClient(json.dumps(report))
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(REVIEW_PAYLOAD)

    assert result == report
    assert len(hermes.calls) == 1
    assert "general code reviewer" in hermes.calls[0][0]["content"]
    assert "Task: review" in hermes.calls[0][1]["content"]
    assert "Daysun-Labs/astate-brain" in hermes.calls[0][1]["content"]


def test_review_malformed_hermes_output_becomes_unknown_report() -> None:
    hermes = FakeHermesClient("this is not json")
    service = ProposalService(config(), hermes_client=hermes)

    result = service.handle(REVIEW_PAYLOAD)

    assert result["score"] == -1
    assert result["findings"] == []
    assert "Malformed Hermes review" in result["summary"]


def test_review_score_coercion_accepts_string_and_float_and_clamps() -> None:
    # Harmless formatting drift ("4"/4.0) must be preserved, not collapsed to -1;
    # out-of-range clamps high, negative/bool are the unknown sentinel.
    for raw, expected in [("4", 4), (4.0, 4), (7, 5), (-2, -1), (True, -1)]:
        hermes = FakeHermesClient(
            json.dumps({"score": raw, "summary": "s", "findings": []})
        )
        service = ProposalService(config(), hermes_client=hermes)
        result = service.handle(REVIEW_PAYLOAD)
        assert result["score"] == expected


def test_review_request_requires_review_task_and_prompt_payload_round_trips() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate(REVIEW_PAYLOAD | {"task": "code_fix"})

    request = ReviewRequest.model_validate(REVIEW_PAYLOAD)

    payload = request.prompt_payload()
    assert payload["task"] == "review"
    assert payload["diff_summary"] == REVIEW_PAYLOAD["diff_summary"]
    assert payload["repo_context"] == REVIEW_PAYLOAD["repo_context"]


def test_review_oversize_diff_summary_becomes_unknown_without_hermes_call() -> None:
    hermes = FakeHermesClient('{"score":0,"summary":"should not run","findings":[]}')
    service = ProposalService(config(), hermes_client=hermes)
    payload = REVIEW_PAYLOAD | {"diff_summary": "x" * (config().max_diff_summary_chars + 1)}

    result = service.handle(payload)

    assert result == {
        "score": -1,
        "summary": "review input too large.",
        "findings": [],
    }
    assert hermes.calls == []


@pytest.mark.parametrize(
    "metadata",
    [
        BASE_PAYLOAD["metadata"] | {"repo": "evil/repo"},
        {k: v for k, v in BASE_PAYLOAD["metadata"].items() if k != "repo"},
    ],
)
def test_review_repo_allowlist_blocks_unapproved_or_missing_repo(metadata: dict[str, object]) -> None:
    hermes = FakeHermesClient('{"score":0,"summary":"should not run","findings":[]}')
    service = ProposalService(config(), hermes_client=hermes)

    with pytest.raises(ForbiddenRequest):
        service.handle(REVIEW_PAYLOAD | {"metadata": metadata})

    assert hermes.calls == []
