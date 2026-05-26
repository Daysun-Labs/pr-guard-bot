"""Drift detection — Sub-AC 2.

Pure function ``detect_drift`` compares a parsed PRD/SEED ``SpecBundle``
against a ``NormalizedDiff`` parsed from a PR and returns a list of
``DriftItem`` records — one per requirement the PR fails to address.

This is intentionally a static, syntactic check that piggybacks on
``spec_matcher.match_requirements``. A requirement is reported as drift
when the matcher classifies it as unmet (no file/symbol/token evidence
in the diff). Each drift item carries enough provenance (source file +
line + verbatim quote) that downstream PR comments and fix-PR
generation can cite the exact PRD/SEED line.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Iterable

from .diff_extractor import NormalizedDiff
from .spec_matcher import MatchResult, match_requirements
from .spec_parser import Requirement, SpecBundle


# Severity ranking by requirement kind. The classifier in Sub-AC 4 will
# refine this; here we provide a stable default so downstream consumers
# can sort drift items deterministically.
_SEVERITY_BY_KIND = {
    "acceptance": "high",
    "constraint": "high",
    "non_goal": "medium",
    "intent": "medium",
}


@dataclass(frozen=True)
class DriftItem:
    """A single PRD/SEED requirement the PR diff fails to address."""

    type: str  # "missing_requirement"
    severity: str  # "high" | "medium" | "low"
    source: str  # "prd" | "seed"
    source_file: str
    section: str
    kind: str
    quote: str
    line: int
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def detect_drift(
    spec: SpecBundle | Iterable[Requirement],
    diff: NormalizedDiff,
    *,
    threshold: float = 0.34,
) -> list[DriftItem]:
    """Return drift items for every requirement the diff does not address.

    Args:
        spec: Either a parsed ``SpecBundle`` or any iterable of
            ``Requirement`` items.
        diff: A ``NormalizedDiff`` parsed from the PR's unified diff.
        threshold: Token-coverage threshold passed to the matcher.

    Returns:
        A list of ``DriftItem`` — empty when every requirement is
        satisfied by the diff (i.e. zero-drift case).
    """
    if isinstance(spec, SpecBundle):
        requirements: list[Requirement] = list(spec.requirements)
    else:
        requirements = list(spec)

    report = match_requirements(requirements, diff, threshold=threshold)

    drifts: list[DriftItem] = []
    for m in report.unmet:
        drifts.append(_to_drift_item(m))
    return drifts


def filter_actionable_drift(
    drifts: Iterable[DriftItem],
) -> tuple[list[DriftItem], dict[str, int]]:
    """Return only items the PR could plausibly act on, plus suppression stats.

    Suppressed by default:
      - ``kind == "non_goal"`` — definitionally something the bot should NOT do
      - ``score == 0`` — no token/file/symbol overlap with the diff, i.e. the
        requirement is simply unrelated to this PR's scope. Carrying these into
        the PR comment produces noise on every small PR.

    Returns ``(actionable, suppressed)`` where ``suppressed`` is a count map::

        {"non_goal": N, "unrelated": M}
    """
    actionable: list[DriftItem] = []
    suppressed = {"non_goal": 0, "unrelated": 0}
    for d in drifts:
        if d.kind == "non_goal":
            suppressed["non_goal"] += 1
            continue
        if d.score <= 0.0:
            suppressed["unrelated"] += 1
            continue
        actionable.append(d)
    return actionable, suppressed


def _to_drift_item(m: MatchResult) -> DriftItem:
    req = m.requirement
    severity = _SEVERITY_BY_KIND.get(req.kind, "medium")
    return DriftItem(
        type="missing_requirement",
        severity=severity,
        source=req.source,
        source_file=req.source_file,
        section=req.section,
        kind=req.kind,
        quote=req.text,
        line=req.line,
        score=m.score,
    )
