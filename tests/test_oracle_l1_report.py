"""Tests for L1 oracle report generator — Sub-AC 4."""
from __future__ import annotations

from pr_guard.spec_parser import Requirement
from pr_guard.spec_matcher import MatchEvidence, MatchReport, MatchResult
from pr_guard.oracle_l1_report import (
    ORACLE_LEVEL,
    VERDICT_FAIL,
    VERDICT_PASS,
    build_l1_report,
    validate_report_schema,
)


def _req(text: str, source: str = "prd", line: int = 1) -> Requirement:
    return Requirement(
        text=text,
        source=source,
        source_file=f"{source.upper()}.md",
        section="Acceptance",
        kind="acceptance",
        line=line,
    )


def _result(req: Requirement, *, satisfied: bool, score: float = 0.5) -> MatchResult:
    ev = MatchEvidence(
        matched_files=["src/foo.py"] if satisfied else [],
        matched_symbols=[],
        matched_tokens=["foo"] if satisfied else [],
    )
    return MatchResult(requirement=req, satisfied=satisfied, score=score, evidence=ev)


def test_build_report_all_satisfied_yields_pass_verdict():
    r1 = _result(_req("ship feature A"), satisfied=True, score=0.8)
    r2 = _result(_req("ship feature B", source="seed"), satisfied=True, score=0.9)
    report = build_l1_report(MatchReport(satisfied=[r1, r2], unmet=[]))

    d = report.to_dict()
    assert d["oracle_level"] == ORACLE_LEVEL
    assert d["verdict"] == VERDICT_PASS
    assert d["summary"] == {"total": 2, "satisfied": 2, "violated": 0, "pass_rate": 1.0}
    assert d["violations"] == []
    assert len(d["satisfied"]) == 2
    assert validate_report_schema(d) == []


def test_build_report_with_violations_yields_fail_verdict():
    sat = _result(_req("done thing"), satisfied=True, score=0.7)
    bad = _result(_req("missing thing", source="seed", line=42), satisfied=False, score=0.1)
    report = build_l1_report(MatchReport(satisfied=[sat], unmet=[bad]))

    d = report.to_dict()
    assert d["verdict"] == VERDICT_FAIL
    assert d["summary"]["total"] == 2
    assert d["summary"]["satisfied"] == 1
    assert d["summary"]["violated"] == 1
    assert d["summary"]["pass_rate"] == 0.5

    v = d["violations"][0]
    assert v["source"] == "seed"
    assert v["source_file"] == "SEED.md"
    assert v["line"] == 42
    assert v["requirement"] == "missing thing"
    assert v["score"] == 0.1
    assert v["evidence"] == {"matched_files": [], "matched_symbols": [], "matched_tokens": []}

    assert validate_report_schema(d) == []


def test_build_report_empty_inputs_passes():
    report = build_l1_report(MatchReport(satisfied=[], unmet=[]))
    d = report.to_dict()
    assert d["verdict"] == VERDICT_PASS
    assert d["summary"]["total"] == 0
    assert d["summary"]["pass_rate"] == 1.0
    assert validate_report_schema(d) == []


def test_validate_report_schema_detects_errors():
    bad = {
        "oracle_level": "L2",
        "verdict": "maybe",
        "summary": {"total": 1, "satisfied": 0, "violated": 0, "pass_rate": 2.0},
        "violations": "nope",
        "satisfied": [],
    }
    errors = validate_report_schema(bad)
    assert any("oracle_level" in e for e in errors)
    assert any("verdict" in e for e in errors)
    assert any("pass_rate" in e for e in errors)
    assert any("violations must be list" in e for e in errors)
    assert any("satisfied + summary.violated" in e for e in errors)


def test_validate_report_schema_rejects_non_dict():
    assert validate_report_schema("nope")  # non-empty error list


def test_validate_report_schema_detects_verdict_violation_mismatch():
    sat_item = {
        "source": "prd",
        "source_file": "PRD.md",
        "section": "x",
        "line": 1,
        "requirement": "r",
        "score": 0.5,
        "evidence": {"matched_files": [], "matched_symbols": [], "matched_tokens": []},
    }
    report = {
        "oracle_level": "L1",
        "verdict": "pass",
        "summary": {"total": 1, "satisfied": 0, "violated": 1, "pass_rate": 0.0},
        "violations": [sat_item],
        "satisfied": [],
    }
    errors = validate_report_schema(report)
    assert any("verdict 'pass' but violations is non-empty" in e for e in errors)
