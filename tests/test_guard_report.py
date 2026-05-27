from __future__ import annotations

import json

from pr_guard.drift import DriftItem
from pr_guard.guard_report import build_guard_report, write_guard_report


def _drift(*, source: str = "prd", quote: str = "implement audit logging") -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=f"{source.upper()}.md",
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=7,
        score=0.42,
    )


def test_report_passes_when_no_actionable_drift() -> None:
    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[],
        fix_prs=[],
        suppressed={"unrelated": 2, "non_goal": 1},
    )

    assert report["schema_version"] == 1
    assert report["repo"] == "octo/app"
    assert report["pr_number"] == 12
    assert report["verdict"] == "pass"
    assert report["drift_count"] == 0
    assert report["fix_pr_count"] == 0
    assert report["drifts"] == []
    assert report["fix_prs"] == []
    assert report["suppressed"] == {"unrelated": 2, "non_goal": 1}
    assert "No actionable drift" in report["summary"]


def test_report_needs_fix_review_when_fix_prs_created() -> None:
    drift = _drift(source="seed", quote="document OAuth setup")

    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[drift],
        fix_prs=[(drift, 99)],
        suppressed={"unrelated": 0, "non_goal": 0},
    )

    assert report["verdict"] == "needs_fix_review"
    assert report["drift_count"] == 1
    assert report["fix_pr_count"] == 1
    assert report["drifts"] == [drift.to_dict()]
    assert report["fix_prs"] == [{"pr_number": 99, "drift": drift.to_dict()}]
    assert "1 fix PR" in report["summary"]


def test_report_fails_when_actionable_drift_remains_without_fix_prs() -> None:
    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[_drift(), _drift(quote="add trace IDs")],
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
    )

    assert report["verdict"] == "fail"
    assert report["drift_count"] == 2
    assert "2 actionable drift" in report["summary"]


def test_write_guard_report_creates_json_file(tmp_path) -> None:
    path = tmp_path / "nested" / "pr-guard-report.json"
    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[],
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
    )

    write_guard_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
