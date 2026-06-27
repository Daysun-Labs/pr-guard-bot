"""Unit tests for comment_format Markdown rendering."""
from __future__ import annotations

from pr_guard.comment_format import format_drift_comment, format_review_comment
from pr_guard.drift import DriftItem
from pr_guard.review import ReviewFinding, ReviewReport


def _drift(**overrides) -> DriftItem:
    base = dict(
        type="missing_requirement",
        severity="high",
        source="prd",
        source_file="PRD.md",
        section="Acceptance",
        kind="acceptance",
        quote="The system must support webhook signature verification.",
        line=42,
        score=0.1,
    )
    base.update(overrides)
    return DriftItem(**base)


def test_empty_drift_returns_no_drift_message():
    body = format_drift_comment([])
    assert body.startswith("## PR Guard")
    assert "No drift detected" in body
    assert body.endswith("\n")


def test_returns_string():
    body = format_drift_comment([_drift()])
    assert isinstance(body, str)


def test_includes_header_and_summary_count():
    body = format_drift_comment([_drift(), _drift(severity="medium", source="seed", source_file="SEED.md")])
    assert "## PR Guard — PRD/SEED Drift Report" in body
    assert "Found **2** drift finding" in body
    assert "**high**: 1" in body
    assert "**medium**: 1" in body
    assert "Classifier: `spec-violation`: 2" in body


def test_groups_by_source_prd_and_seed():
    body = format_drift_comment([
        _drift(source="prd", source_file="PRD.md", quote="A prd req"),
        _drift(source="seed", source_file="SEED.md", quote="A seed req", severity="medium", kind="constraint"),
    ])
    assert "### PRD drift (1)" in body
    assert "### SEED drift (1)" in body
    assert "A prd req" in body
    assert "A seed req" in body


def test_quote_and_location_rendered():
    body = format_drift_comment([_drift(source_file="PRD.md", line=99, quote="must verify HMAC")])
    assert "`PRD.md:99`" in body
    assert "`spec-violation`" in body
    assert "> must verify HMAC" in body


def test_severity_ordering_high_before_medium():
    body = format_drift_comment([
        _drift(severity="medium", line=10, quote="med one"),
        _drift(severity="high", line=20, quote="high one"),
    ])
    # Both PRD; high listed before medium
    assert body.index("high one") < body.index("med one")


def test_accepts_dict_items():
    body = format_drift_comment([
        {
            "type": "missing_requirement",
            "severity": "low",
            "source": "seed",
            "source_file": "SEED.md",
            "section": "Constraints",
            "kind": "constraint",
            "quote": "no external infra",
            "line": 3,
            "score": 0.0,
        }
    ])
    assert "no external infra" in body
    assert "### SEED drift (1)" in body


def test_custom_title():
    body = format_drift_comment([], title="Custom Title")
    assert "## Custom Title" in body


def test_pure_function_no_mutation():
    items = [_drift()]
    snapshot = list(items)
    format_drift_comment(items)
    assert items == snapshot


def test_multiline_quote_collapsed():
    body = format_drift_comment([_drift(quote="line1\nline2")])
    assert "line1 line2" in body
    assert "\n  > line1\n" not in body


def _finding(**overrides) -> ReviewFinding:
    base = dict(
        category="bug",
        severity="error",
        file="src/app.py",
        line=12,
        quote="return None",
        suggestion="Return the parsed payload.",
    )
    base.update(overrides)
    return ReviewFinding(**base)


def _review_report(**overrides) -> ReviewReport:
    base = dict(
        findings=(_finding(),),
        score=4,
        summary="One deterministic gate finding needs attention.",
    )
    base.update(overrides)
    return ReviewReport(**base)


def test_review_comment_includes_score_and_summary():
    body = format_review_comment(_review_report(score=3, summary="Review score is gated."))

    assert "## PR Guard — Review" in body
    assert "**Score: 3/5**" in body
    assert "Review score is gated." in body


def test_review_comment_renders_unknown_score():
    body = format_review_comment(_review_report(score=-1))

    assert "**Score: unknown**" in body
    assert "**Score: -1/5**" not in body


def test_review_comment_filters_to_error_or_security_findings_only():
    body = format_review_comment(
        _review_report(
            findings=(
                _finding(category="bug", severity="error", suggestion="Fix the crash."),
                _finding(
                    category="quality",
                    severity="warn",
                    file="src/slow.py",
                    line=8,
                    suggestion="Consider cleanup.",
                ),
                _finding(
                    category="security",
                    severity="info",
                    file="src/auth.py",
                    line=44,
                    suggestion="Double-check token handling.",
                ),
            )
        )
    )

    assert "- error · bug · src/app.py:12 — Fix the crash." in body
    assert "- info · security · src/auth.py:44 — Double-check token handling." in body
    assert "Consider cleanup." not in body


def test_review_comment_empty_findings_says_no_score_gate_findings():
    body = format_review_comment(_review_report(findings=()))

    assert "No error/security findings" in body
    assert body.endswith("\n")


def test_review_comment_omits_empty_summary():
    body = format_review_comment(_review_report(summary=""))

    assert "One deterministic gate finding needs attention." not in body
    assert "deterministic score gate" in body
