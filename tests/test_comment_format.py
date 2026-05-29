"""Unit tests for comment_format.format_drift_comment (Sub-AC 1)."""
from __future__ import annotations

from pr_guard.comment_format import format_drift_comment
from pr_guard.drift import DriftItem


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
