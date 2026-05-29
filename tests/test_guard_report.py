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


def test_report_passes_when_only_advisory_drift_without_blocking() -> None:
    # Advisory (static token-coverage) drift is surfaced but must not fail CI
    # unless promoted to blocking — this is the core false-positive fix.
    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[_drift(), _drift(quote="add trace IDs")],
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
    )

    assert report["verdict"] == "pass"
    assert report["drift_count"] == 2
    assert report["blocking_count"] == 0
    assert "advisory drift" in report["summary"]
    assert "non-blocking" in report["summary"]


def test_report_fails_when_blocking_drift_remains_without_fix_prs() -> None:
    blockers = [_drift(), _drift(quote="add trace IDs")]
    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=blockers,
        fix_prs=[],
        suppressed={"unrelated": 0, "non_goal": 0},
        blocking_drifts=blockers,
    )

    assert report["verdict"] == "fail"
    assert report["drift_count"] == 2
    assert report["blocking_count"] == 2
    assert "2 blocking drift" in report["summary"]


def test_report_summary_describes_reused_fix_pr_without_claiming_creation() -> None:
    drift = _drift(source="seed", quote="document OAuth setup")

    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[drift],
        fix_prs=[
            {
                "drift": drift,
                "status": "reused",
                "branch": "pr-guard/seed-fix/seed-document-oauth-1234",
                "pr_number": 99,
                "reason": "existing open PR #99 already uses branch; reused instead",
            }
        ],
        suppressed={"unrelated": 0, "non_goal": 0},
    )

    assert report["verdict"] == "needs_fix_review"
    assert report["fix_pr_count"] == 1
    assert "1 fix PR" in report["summary"]
    assert "ready/reused for review" in report["summary"]
    assert "created for review" not in report["summary"]


def test_report_preserves_fix_pr_status_and_skip_reason() -> None:
    drift = _drift(source="seed", quote="document OAuth setup")

    report = build_guard_report(
        repo="octo/app",
        pr_number=12,
        actionable_drifts=[drift],
        fix_prs=[
            {
                "drift": drift,
                "status": "skipped",
                "branch": "pr-guard/seed-fix/seed-document-oauth-1234",
                "pr_number": None,
                "reason": "could not create a unique branch after 2 attempt(s)",
            }
        ],
        suppressed={"unrelated": 0, "non_goal": 0},
        blocking_drifts=[drift],
    )

    assert report["verdict"] == "fail"
    assert report["fix_pr_count"] == 0
    assert report["fix_prs"][0]["status"] == "skipped"
    assert "unique branch" in report["fix_prs"][0]["reason"]


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
