"""Structured PR Guard report and CI verdict helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .drift import DriftItem

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
) -> dict[str, Any]:
    """Build the stable JSON-serializable report emitted by the CI gate.

    Verdict rules are intentionally simple and deterministic:
      - ``pass`` when there is no actionable drift.
      - ``needs_fix_review`` when one or more fix PRs were generated.
      - ``fail`` when actionable drift remains and no fix PR was generated.
    """
    drift_items = list(actionable_drifts)
    fix_items = [_normalize_fix_pr(item) for item in fix_prs]
    drift_count = len(drift_items)
    fix_pr_count = sum(1 for item in fix_items if item.get("pr_number") is not None)
    verdict = determine_verdict(drift_count=drift_count, fix_pr_count=fix_pr_count)

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": repo,
        "pr_number": pr_number,
        "verdict": verdict,
        "drift_count": drift_count,
        "fix_pr_count": fix_pr_count,
        "drifts": [d.to_dict() for d in drift_items],
        "fix_prs": fix_items,
        "suppressed": _normalize_suppressed(suppressed),
        "summary": _summary(verdict, drift_count=drift_count, fix_pr_count=fix_pr_count),
    }


def determine_verdict(*, drift_count: int, fix_pr_count: int) -> str:
    if drift_count <= 0:
        return PASS
    if fix_pr_count > 0:
        return NEEDS_FIX_REVIEW
    return FAIL


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


def _normalize_suppressed(suppressed: dict[str, int] | None) -> dict[str, int]:
    suppressed = suppressed or {}
    return {
        "unrelated": int(suppressed.get("unrelated", 0)),
        "non_goal": int(suppressed.get("non_goal", 0)),
    }


def _summary(verdict: str, *, drift_count: int, fix_pr_count: int) -> str:
    if verdict == PASS:
        return "No actionable drift detected."
    if verdict == NEEDS_FIX_REVIEW:
        noun = "fix PR" if fix_pr_count == 1 else "fix PRs"
        return f"{drift_count} actionable drift item(s) detected; {fix_pr_count} {noun} ready/reused for review."
    return f"{drift_count} actionable drift item(s) detected; no fix PRs were created."
