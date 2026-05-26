"""Drift classification — Sub-AC 3.

Pure function ``classify_drift`` maps a ``DriftItem`` (or any
dict-like equivalent) to a stable category string used by downstream
fix-PR routing (code-fix vs seed-fix) and reporting.

Categories
----------
- ``spec-missing``    : the spec line itself has no corresponding code
                        evidence at all — diff doesn't touch anything
                        related (score == 0).
- ``spec-violation``  : the diff *does* touch the area but the
                        requirement is only partially addressed
                        (0 < score < threshold) — looks like the PR
                        breaks/contradicts the spec.
- ``spec-ambiguous``  : the requirement quote is too vague to evaluate
                        (empty quote or only stopwords) — surfaces as
                        a hint to clarify the spec, not the code.
- ``unknown``         : fallback for malformed inputs.

The function is intentionally *pure*: no I/O, no globals, no mutation
of the input. Inputs are either a ``DriftItem`` instance or a plain
mapping with the same keys.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Iterable

from .drift import DriftItem


CATEGORIES = ("spec-missing", "spec-violation", "spec-ambiguous", "unknown")


def _as_mapping(item: DriftItem | Mapping) -> Mapping:
    if isinstance(item, DriftItem):
        return item.to_dict()
    if isinstance(item, Mapping):
        return item
    raise TypeError(f"Unsupported drift item type: {type(item)!r}")


def classify_drift(
    item: DriftItem | Mapping,
    *,
    threshold: float = 0.34,
) -> str:
    """Classify a single drift item into a category string.

    Args:
        item: A ``DriftItem`` or mapping with ``score`` and ``quote``.
        threshold: Same coverage threshold used by the matcher; scores
            at-or-above the threshold should not normally appear here
            (they wouldn't be drift), but we treat them defensively as
            ``unknown``.

    Returns:
        One of :data:`CATEGORIES`.
    """
    try:
        data = _as_mapping(item)
    except TypeError:
        return "unknown"

    quote = str(data.get("quote", "")).strip()
    if not quote:
        return "spec-ambiguous"

    # quote present but only stopword-ish tokens (<= 2 alpha tokens of len>=3)
    meaningful = [t for t in quote.split() if len(t) >= 3 and t.isalpha()]
    if len(meaningful) < 2:
        return "spec-ambiguous"

    try:
        score = float(data.get("score", 0.0))
    except (TypeError, ValueError):
        return "unknown"

    if score <= 0.0:
        return "spec-missing"
    if 0.0 < score < threshold:
        return "spec-violation"
    return "unknown"


def classify_all(
    items: Iterable[DriftItem | Mapping],
    *,
    threshold: float = 0.34,
) -> list[tuple[str, DriftItem | Mapping]]:
    """Classify every drift item; return list of (category, item) tuples."""
    return [(classify_drift(i, threshold=threshold), i) for i in items]
