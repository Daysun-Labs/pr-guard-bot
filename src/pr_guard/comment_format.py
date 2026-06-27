"""Pure Markdown formatter for PR comment bodies from drift findings.

Sub-AC 1: Given a list of ``DriftItem`` records (or dicts with the same
shape), return a Markdown string suitable for posting as a GitHub PR
review comment. Pure function — no I/O.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Any

from .drift import DriftItem
from .drift_classifier import classify_drift
from .review import ReviewReport


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def _as_dict(item: Any) -> Mapping[str, Any]:
    if isinstance(item, DriftItem):
        return item.to_dict()
    if isinstance(item, Mapping):
        return item
    raise TypeError(f"Unsupported drift item type: {type(item)!r}")


def format_drift_comment(drifts: Iterable[Any], *, title: str = "PR Guard — PRD/SEED Drift Report") -> str:
    """Render a Markdown body for a PR comment from drift items.

    - Empty input -> a short "no drift detected" body.
    - Otherwise: header + summary counts + grouped sections by source
      (PRD/SEED), sorted by severity then line.
    """
    items = [_as_dict(d) for d in drifts]

    lines: list[str] = [f"## {title}", ""]

    if not items:
        lines.append("✅ No drift detected — every PRD/SEED requirement is addressed by this PR.")
        return "\n".join(lines).rstrip() + "\n"

    # Summary counts
    by_sev: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for it in items:
        by_sev[it["severity"]] = by_sev.get(it["severity"], 0) + 1
        category = classify_drift(it)
        by_category[category] = by_category.get(category, 0) + 1
    summary_parts = [
        f"{_SEVERITY_EMOJI.get(sev, '•')} **{sev}**: {by_sev[sev]}"
        for sev in ("high", "medium", "low")
        if sev in by_sev
    ]
    lines.append(f"Found **{len(items)}** drift finding(s) — " + ", ".join(summary_parts))
    category_parts = [
        f"`{category}`: {by_category[category]}"
        for category in ("spec-missing", "spec-violation", "spec-ambiguous", "unknown")
        if category in by_category
    ]
    if category_parts:
        lines.append("Classifier: " + ", ".join(category_parts))
    lines.append("")

    def _sort_key(it: Mapping[str, Any]):
        return (
            _SEVERITY_ORDER.get(it.get("severity", "low"), 99),
            str(it.get("source_file", "")),
            int(it.get("line", 0) or 0),
        )

    for source_label, source_key in (("PRD", "prd"), ("SEED", "seed")):
        group = [it for it in items if it.get("source") == source_key]
        if not group:
            continue
        group.sort(key=_sort_key)
        lines.append(f"### {source_label} drift ({len(group)})")
        lines.append("")
        for it in group:
            sev = it.get("severity", "low")
            emoji = _SEVERITY_EMOJI.get(sev, "•")
            quote = str(it.get("quote", "")).strip().replace("\n", " ")
            loc = f"`{it.get('source_file','?')}:{it.get('line','?')}`"
            section = it.get("section") or ""
            kind = it.get("kind") or ""
            category = classify_drift(it)
            lines.append(
                f"- {emoji} **{sev.upper()}** {loc} _{kind}_ "
                f"`{category}` — {section}"
            )
            if quote:
                lines.append(f"  > {quote}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_review_comment(report: ReviewReport, *, title: str = "PR Guard — Review") -> str:
    """Render the deterministic review score-gate comment."""
    lines: list[str] = [f"## {title}", ""]
    score = "unknown" if report.score == -1 else f"{report.score}/5"
    lines.append(f"**Score: {score}**")

    summary = report.summary.strip()
    if summary:
        lines.append("")
        lines.append(summary)

    lines.append("")
    gate_findings = [
        finding
        for finding in report.findings
        if finding.severity == "error" or finding.category == "security"
    ]
    if gate_findings:
        for finding in gate_findings:
            suggestion = finding.suggestion.strip().replace("\n", " ")
            if not suggestion:
                suggestion = "No suggestion provided."
            lines.append(
                f"- {finding.severity} · {finding.category} · "
                f"{finding.file}:{finding.line} — {suggestion}"
            )
    else:
        lines.append("No error/security findings for the deterministic score gate.")

    lines.append("")
    lines.append(
        "_General advisory review is handled by Codex GitHub review; "
        "this comment is the deterministic score gate._"
    )
    return "\n".join(lines).rstrip() + "\n"
