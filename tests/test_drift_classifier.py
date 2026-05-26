"""Sub-AC 3: classify_drift mapping tests."""

from __future__ import annotations

import pytest

from pr_guard.drift import DriftItem
from pr_guard.drift_classifier import CATEGORIES, classify_all, classify_drift


def _item(*, quote="must support webhook signature verification", score=0.0) -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source="prd",
        source_file="PRD.md",
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=10,
        score=score,
    )


def test_score_zero_is_spec_missing():
    assert classify_drift(_item(score=0.0)) == "spec-missing"


def test_partial_score_is_spec_violation():
    assert classify_drift(_item(score=0.2), threshold=0.34) == "spec-violation"


def test_score_at_or_above_threshold_is_unknown():
    # Not normally a drift item, but classifier handles defensively
    assert classify_drift(_item(score=0.5), threshold=0.34) == "unknown"


def test_empty_quote_is_spec_ambiguous():
    assert classify_drift(_item(quote="   ", score=0.0)) == "spec-ambiguous"


def test_stopword_only_quote_is_spec_ambiguous():
    assert classify_drift(_item(quote="a the", score=0.0)) == "spec-ambiguous"


def test_mapping_input_supported():
    payload = {"quote": "deploy via github actions only", "score": 0.0}
    assert classify_drift(payload) == "spec-missing"


def test_invalid_input_returns_unknown():
    assert classify_drift(42) == "unknown"  # type: ignore[arg-type]


def test_malformed_score_returns_unknown():
    assert classify_drift({"quote": "must verify github webhook", "score": "abc"}) == "unknown"


def test_classify_all_returns_pairs():
    items = [_item(score=0.0), _item(score=0.1)]
    result = classify_all(items)
    assert [c for c, _ in result] == ["spec-missing", "spec-violation"]
    assert all(c in CATEGORIES for c, _ in result)


def test_categories_are_stable_set():
    assert set(CATEGORIES) == {"spec-missing", "spec-violation", "spec-ambiguous", "unknown"}


@pytest.mark.parametrize(
    "score,expected",
    [(0.0, "spec-missing"), (0.01, "spec-violation"), (0.33, "spec-violation"), (0.34, "unknown")],
)
def test_score_mapping_boundaries(score, expected):
    assert classify_drift(_item(score=score), threshold=0.34) == expected
