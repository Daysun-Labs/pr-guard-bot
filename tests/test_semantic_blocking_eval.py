from __future__ import annotations

from dataclasses import dataclass

import pytest

from pr_guard.drift import BlockingDriftDecision, DriftItem, select_blocking_drift_decisions
from pr_guard.guard_report import build_guard_report


@dataclass(frozen=True)
class SemanticCase:
    name: str
    drift: DriftItem
    diff_summary: str
    provider_blocking: bool
    provider_reason: str
    expected_verdict: str
    expected_blocking_count: int


def _drift(*, quote: str, score: float = 0.33) -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source="prd",
        source_file="PRD.md",
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=42,
        score=score,
    )


GOLD_CASES = [
    SemanticCase(
        name="docs_config_noise_stays_green",
        drift=_drift(quote="The app must verify webhook signatures before processing payloads."),
        diff_summary="FILE docs/operations/pr-guard-required-check.md (modified, +8, -2)",
        provider_blocking=False,
        provider_reason="Docs-only change does not prove a scoped implementation violation.",
        expected_verdict="pass",
        expected_blocking_count=0,
    ),
    SemanticCase(
        name="scoped_code_violation_blocks",
        drift=_drift(quote="The app must verify webhook signatures before processing payloads."),
        diff_summary=(
            "FILE src/webhook_handler.py (modified, +12, -3)\n"
            "symbols: process_webhook\n"
            "added:\n"
            "def process_webhook(payload):\n"
            "    return handle_payload(payload)"
        ),
        provider_blocking=True,
        provider_reason="Webhook handler changed but signature verification is still absent.",
        expected_verdict="fail",
        expected_blocking_count=1,
    ),
]


class FixtureProvider:
    def __init__(self, *, should_block: bool, reason: str) -> None:
        self.should_block = should_block
        self.reason = reason

    def classify_blocking_drift(
        self,
        advisory: list[DriftItem],
        *,
        diff_summary: str | None = None,
    ) -> list[BlockingDriftDecision]:
        if not self.should_block:
            return []
        return [
            BlockingDriftDecision(
                drift=advisory[0],
                reason=self.reason,
            )
        ]


@pytest.mark.parametrize("case", GOLD_CASES, ids=[case.name for case in GOLD_CASES])
def test_semantic_blocking_gold_cases(case: SemanticCase) -> None:
    decisions = select_blocking_drift_decisions(
        [case.drift],
        provider=FixtureProvider(
            should_block=case.provider_blocking,
            reason=case.provider_reason,
        ),
        diff_summary=case.diff_summary,
    )

    report = build_guard_report(
        repo="octo/app",
        pr_number=42,
        actionable_drifts=[case.drift],
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
        blocking_drifts=decisions,
    )

    assert report["verdict"] == case.expected_verdict
    assert report["blocking_count"] == case.expected_blocking_count
    if case.expected_blocking_count:
        assert report["blocking_drifts"][0]["reason"] == case.provider_reason


def test_semantic_blocking_provider_failure_keeps_ci_green() -> None:
    class FailingProvider:
        def classify_blocking_drift(self, advisory, *, diff_summary=None):
            raise RuntimeError("LLM timeout")

    drift = _drift(quote="The app must verify webhook signatures before processing payloads.")
    decisions = select_blocking_drift_decisions([drift], provider=FailingProvider())

    report = build_guard_report(
        repo="octo/app",
        pr_number=42,
        actionable_drifts=[drift],
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
        blocking_drifts=decisions,
    )

    assert report["verdict"] == "pass"
    assert report["blocking_count"] == 0
