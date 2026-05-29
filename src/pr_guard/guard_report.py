"""Structured PR Guard report and CI verdict helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .drift import BlockingDriftDecision, DriftItem

SCHEMA_VERSION = 1
PASS = "pass"
FAIL = "fail"
NEEDS_FIX_REVIEW = "needs_fix_review"


def build_guard_report(
    *,
    repo: str,
    pr_number: int,
    actionable_drifts: Iterable[DriftItem],
    fix_prs: Iterable[tuple[DriftItem, int] | dict[str, Any]],
    suppressed: dict[str, int] | None = None,
    blocking_drifts: Iterable[DriftItem | BlockingDriftDecision | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the stable JSON-serializable report emitted by the CI gate.

    ``actionable_drifts`` are *advisory* findings — surfaced for humans in the
    PR comment and recorded in ``drift_count``/``drifts``, but they do not by
    themselves fail the check. ``blocking_drifts`` is the (usually smaller,
    higher-confidence) subset that drives a failing verdict; when omitted there
    is no blocking drift and an advisory-only report passes. See
    ``drift.select_blocking_drift`` for why the static matcher leaves blocking
    drift empty by default.

    Verdict rules are intentionally simple and deterministic:
      - ``needs_fix_review`` when one or more fix PRs were generated.
      - ``fail`` when blocking drift remains and no fix PR was generated.
      - ``pass`` otherwise (including advisory-only drift with no fix PRs).
    """
    drift_items = list(actionable_drifts)
    block_items = [_normalize_blocking_drift(item) for item in (blocking_drifts or [])]
    fix_items = [_normalize_fix_pr(item) for item in fix_prs]
    drift_count = len(drift_items)
    blocking_count = len(block_items)
    fix_pr_count = sum(1 for item in fix_items if item.get("pr_number") is not None)
    verdict = determine_verdict(blocking_count=blocking_count, fix_pr_count=fix_pr_count)

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": repo,
        "pr_number": pr_number,
        "verdict": verdict,
        "drift_count": drift_count,
        "blocking_count": blocking_count,
        "fix_pr_count": fix_pr_count,
        "drifts": [d.to_dict() for d in drift_items],
        "blocking_drifts": block_items,
        "fix_prs": fix_items,
        "suppressed": _normalize_suppressed(suppressed),
        "summary": _summary(
            verdict,
            drift_count=drift_count,
            blocking_count=blocking_count,
            fix_pr_count=fix_pr_count,
        ),
    }


def determine_verdict(*, blocking_count: int, fix_pr_count: int) -> str:
    if fix_pr_count > 0:
        return NEEDS_FIX_REVIEW
    if blocking_count > 0:
        return FAIL
    return PASS


def write_guard_report(report: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalize_fix_pr(item: tuple[DriftItem, int] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, dict):
        pr_number = item.get("pr_number")
        drift = item.get("drift")
        if isinstance(drift, DriftItem):
            drift = drift.to_dict()
        normalized = {"pr_number": pr_number, "drift": drift}
        for key in ("status", "branch", "reason"):
            if key in item:
                normalized[key] = item[key]
        return normalized

    drift, pr_number = item
    return {"pr_number": pr_number, "drift": drift.to_dict()}


def _normalize_blocking_drift(
    item: DriftItem | BlockingDriftDecision | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(item, BlockingDriftDecision):
        return item.to_dict()
    if isinstance(item, DriftItem):
        return {
            "drift": item.to_dict(),
            "reason": "",
            "source": "unknown",
        }
    if isinstance(item, dict):
        drift = item.get("drift")
        if isinstance(drift, DriftItem):
            drift = drift.to_dict()
        return {
            "drift": drift,
            "reason": str(item.get("reason") or ""),
            "source": str(item.get("source") or "unknown"),
        }
    return {"drift": None, "reason": "", "source": "unknown"}


def _normalize_suppressed(suppressed: dict[str, int] | None) -> dict[str, int]:
    suppressed = suppressed or {}
    return {
        "unrelated": int(suppressed.get("unrelated", 0)),
        "non_goal": int(suppressed.get("non_goal", 0)),
    }


def _summary(verdict: str, *, drift_count: int, blocking_count: int, fix_pr_count: int) -> str:
    if verdict == NEEDS_FIX_REVIEW:
        noun = "fix PR" if fix_pr_count == 1 else "fix PRs"
        return (
            f"{drift_count} drift item(s) detected; "
            f"{fix_pr_count} {noun} ready/reused for review."
        )
    if verdict == FAIL:
        return f"{blocking_count} blocking drift item(s) detected; no fix PRs were created."
    if drift_count > 0:
        return f"{drift_count} advisory drift item(s) detected (non-blocking); no blocking drift."
    return "No actionable drift detected."
