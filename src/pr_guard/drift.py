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

from dataclasses import dataclass, asdict
from typing import Any, Iterable

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

# Below this floor, overlap is usually just generic vocabulary ("PR", "user",
# "tool") rather than evidence that the PR is attempting the requirement. Keep
# this below the matcher threshold so relevant partial matches can remain
# actionable instead of being impossible to surface.
ACTIONABLE_SCORE_FLOOR = 0.33


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
      - weak token-only overlap below ``ACTIONABLE_SCORE_FLOOR`` — usually a
        shared word such as "PR" or "user" rather than evidence that this PR is
        attempting the requirement. Carrying these into the PR comment produces
        noise on every small PR.

    Returns ``(actionable, suppressed)`` where ``suppressed`` is a count map::

        {"non_goal": N, "unrelated": M}
    """
    actionable: list[DriftItem] = []
    suppressed = {"non_goal": 0, "unrelated": 0}
    for d in drifts:
        if d.kind == "non_goal":
            suppressed["non_goal"] += 1
            continue
        if d.score < ACTIONABLE_SCORE_FLOOR:
            suppressed["unrelated"] += 1
            continue
        actionable.append(d)
    return actionable, suppressed


def select_blocking_drift(
    advisory: Iterable[DriftItem],
    *,
    fail_on_advisory: bool = False,
    provider: Any | None = None,
    diff_summary: str | None = None,
) -> list[DriftItem]:
    """Return the drift items that should *block* CI (fail the check).

    This is deliberately separate from ``filter_actionable_drift``. The static
    matcher only produces *advisory* drift — token-coverage partial matches
    sitting just below the matcher threshold (see ``ACTIONABLE_SCORE_FLOOR``).
    That signal is far too noisy to fail a required check on: a token-coverage
    score lands in the actionable band only when ~1/3 of a requirement's tokens
    happen to appear as substrings of the diff, which fires on unrelated chores
    (dependency bumps, workflow edits) that merely share vocabulary with a spec
    line. Blocking on it produces frequent false-positive CI failures.

    Advisory drift is now scope-aware (token-coverage evidence is credited only
    to code changes — see ``spec_matcher``), so doc/config-only PRs no longer
    manufacture drift. But the remaining advisory signal is still token-coverage
    based and clusters at the matcher band, so by default nothing here is
    blocking — advisory drift is surfaced in the PR comment and JSON report for
    humans, but the check stays green. A high-confidence source (a semantic/LLM
    oracle) is the intended producer of genuinely blocking drift; this function
    is the seam where it plugs in.

    When an LLM/Hermes provider is supplied, it may promote scoped advisory
    findings to blocking drift via ``classify_blocking_drift``. Provider absence,
    provider implementations without that method, and provider errors all
    degrade to no blocking drift so CI stays green unless there is an explicit
    high-confidence blocking signal.

    Set ``fail_on_advisory`` to opt back into the legacy strict behaviour where
    every advisory item blocks the check.
    """
    items = list(advisory)
    if fail_on_advisory:
        return items
    if not items or provider is None:
        return []

    classifier = getattr(provider, "classify_blocking_drift", None)
    if not callable(classifier):
        return []

    try:
        blocking = classifier(items, diff_summary=diff_summary)
    except Exception:
        return []
    return [item for item in blocking if isinstance(item, DriftItem)]


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
