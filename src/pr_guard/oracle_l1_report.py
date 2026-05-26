"""L1 oracle report generator — Sub-AC 4.

Serializes the static spec/diff matching results (``MatchReport``) into a
single structured *oracle report* object that downstream consumers (PR
comment renderer, drift classifier, fix-PR generator) can rely on.

The report has a stable, well-defined schema:

    {
        "oracle_level": "L1",
        "verdict": "pass" | "fail",
        "summary": {
            "total": int,
            "satisfied": int,
            "violated": int,
            "pass_rate": float,   # 0.0..1.0
        },
        "violations": [
            {
                "source": "prd" | "seed",
                "source_file": str,
                "section": str,
                "line": int,
                "requirement": str,
                "score": float,
                "evidence": {
                    "matched_files": [str, ...],
                    "matched_symbols": [str, ...],
                    "matched_tokens": [str, ...],
                },
            },
            ...
        ],
        "satisfied": [ ...same shape as violations... ],
    }

Pure function. No I/O. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .spec_matcher import MatchReport, MatchResult


ORACLE_LEVEL = "L1"
VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"


@dataclass(frozen=True)
class OracleReport:
    """Serialized L1 oracle outcome — see module docstring for schema."""

    oracle_level: str
    verdict: str
    summary: dict
    violations: list[dict]
    satisfied: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "oracle_level": self.oracle_level,
            "verdict": self.verdict,
            "summary": dict(self.summary),
            "violations": list(self.violations),
            "satisfied": list(self.satisfied),
        }


def build_l1_report(match_report: MatchReport) -> OracleReport:
    """Serialize a ``MatchReport`` into a stable L1 oracle report object.

    Verdict is ``pass`` iff there are zero violations (every requirement
    matched). Otherwise ``fail``.
    """
    violations = [_serialize_result(r) for r in match_report.unmet]
    satisfied = [_serialize_result(r) for r in match_report.satisfied]

    total = len(violations) + len(satisfied)
    pass_rate = (len(satisfied) / total) if total else 1.0
    summary = {
        "total": total,
        "satisfied": len(satisfied),
        "violated": len(violations),
        "pass_rate": round(pass_rate, 4),
    }
    verdict = VERDICT_PASS if not violations else VERDICT_FAIL

    return OracleReport(
        oracle_level=ORACLE_LEVEL,
        verdict=verdict,
        summary=summary,
        violations=violations,
        satisfied=satisfied,
    )


def _serialize_result(result: MatchResult) -> dict:
    req = result.requirement
    ev = result.evidence
    return {
        "source": req.source,
        "source_file": req.source_file,
        "section": req.section,
        "line": req.line,
        "requirement": req.text,
        "score": result.score,
        "evidence": {
            "matched_files": list(ev.matched_files),
            "matched_symbols": list(ev.matched_symbols),
            "matched_tokens": list(ev.matched_tokens),
        },
    }


# ---------------------------------------------------------------------------
# Schema validation helper (used in tests and by callers that persist reports)
# ---------------------------------------------------------------------------


REPORT_TOP_LEVEL_KEYS = {"oracle_level", "verdict", "summary", "violations", "satisfied"}
SUMMARY_KEYS = {"total", "satisfied", "violated", "pass_rate"}
ITEM_KEYS = {"source", "source_file", "section", "line", "requirement", "score", "evidence"}
EVIDENCE_KEYS = {"matched_files", "matched_symbols", "matched_tokens"}


def validate_report_schema(report: Any) -> list[str]:
    """Return a list of schema error messages. Empty list means valid."""
    errors: list[str] = []

    if not isinstance(report, dict):
        return [f"report must be dict, got {type(report).__name__}"]

    missing = REPORT_TOP_LEVEL_KEYS - report.keys()
    if missing:
        errors.append(f"missing top-level keys: {sorted(missing)}")

    if report.get("oracle_level") != ORACLE_LEVEL:
        errors.append(f"oracle_level must be {ORACLE_LEVEL!r}")

    if report.get("verdict") not in (VERDICT_PASS, VERDICT_FAIL):
        errors.append("verdict must be 'pass' or 'fail'")

    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be dict")
    else:
        s_missing = SUMMARY_KEYS - summary.keys()
        if s_missing:
            errors.append(f"summary missing keys: {sorted(s_missing)}")
        if isinstance(summary.get("total"), int) and isinstance(summary.get("satisfied"), int) and isinstance(summary.get("violated"), int):
            if summary["satisfied"] + summary["violated"] != summary["total"]:
                errors.append("summary.satisfied + summary.violated != summary.total")
        pr = summary.get("pass_rate")
        if not isinstance(pr, (int, float)) or not (0.0 <= float(pr) <= 1.0):
            errors.append("summary.pass_rate must be float in [0,1]")

    for bucket in ("violations", "satisfied"):
        items = report.get(bucket)
        if not isinstance(items, list):
            errors.append(f"{bucket} must be list")
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{bucket}[{i}] must be dict")
                continue
            i_missing = ITEM_KEYS - item.keys()
            if i_missing:
                errors.append(f"{bucket}[{i}] missing keys: {sorted(i_missing)}")
            if item.get("source") not in ("prd", "seed"):
                errors.append(f"{bucket}[{i}].source must be 'prd' or 'seed'")
            ev = item.get("evidence")
            if not isinstance(ev, dict):
                errors.append(f"{bucket}[{i}].evidence must be dict")
            else:
                e_missing = EVIDENCE_KEYS - ev.keys()
                if e_missing:
                    errors.append(f"{bucket}[{i}].evidence missing keys: {sorted(e_missing)}")
                for k in EVIDENCE_KEYS:
                    if k in ev and not isinstance(ev[k], list):
                        errors.append(f"{bucket}[{i}].evidence.{k} must be list")

    # Cross-check verdict ↔ violations consistency.
    if isinstance(report.get("violations"), list):
        if report.get("verdict") == VERDICT_PASS and report["violations"]:
            errors.append("verdict 'pass' but violations is non-empty")
        if report.get("verdict") == VERDICT_FAIL and not report["violations"]:
            errors.append("verdict 'fail' but violations is empty")

    return errors
