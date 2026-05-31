"""Sub-AC 2: drift detection tests.

Covers both the drift ≥1 case (PR diff misses a PRD/SEED requirement)
and the drift == 0 case (PR diff covers every requirement).
"""

from __future__ import annotations

from pr_guard.diff_extractor import parse_unified_diff
from pr_guard.drift import (
    BlockingDriftDecision,
    DriftItem,
    detect_drift,
    filter_actionable_drift,
    partition_coverage_only_drift,
    select_blocking_drift,
    select_blocking_drift_decisions,
)
from pr_guard.spec_parser import Requirement, SpecBundle


def _req(text: str, *, source: str = "prd", source_file: str = "PRD.md",
         section: str = "성공 기준", kind: str = "acceptance",
         line: int = 1) -> Requirement:
    return Requirement(
        source=source,
        source_file=source_file,
        section=section,
        kind=kind,
        text=text,
        line=line,
    )


SAMPLE_DIFF = """diff --git a/src/pkg/widget.py b/src/pkg/widget.py
new file mode 100644
--- /dev/null
+++ b/src/pkg/widget.py
@@ -0,0 +1,4 @@
+def render_widget():
+    return "ok"
+
+class WidgetRenderer:
+    pass
"""


def test_zero_drift_when_diff_covers_requirements() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)
    reqs = [
        _req("render_widget function in src/pkg/widget.py must exist"),
        _req("WidgetRenderer class must be defined", line=2),
    ]
    drifts = detect_drift(reqs, diff)
    assert drifts == []


def test_drift_reports_unmet_requirement() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)
    reqs = [
        _req("render_widget function must exist"),  # satisfied
        _req(
            "Slack webhook 알림 모듈이 존재해야 한다",  # unsatisfied
            source="seed",
            source_file="SEED.md",
            section="acceptance_criteria",
            kind="acceptance",
            line=42,
        ),
    ]
    drifts = detect_drift(reqs, diff)
    assert len(drifts) == 1
    item = drifts[0]
    assert isinstance(item, DriftItem)
    assert item.type == "missing_requirement"
    assert item.source == "seed"
    assert item.source_file == "SEED.md"
    assert item.line == 42
    assert "Slack" in item.quote
    assert item.severity in {"high", "medium", "low"}


def test_filter_keeps_detector_unmet_but_relevant_partial_match() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)
    reqs = [
        _req("widget Slack module", source="seed", source_file="SEED.md", line=43),
    ]

    drifts = detect_drift(reqs, diff)
    actionable, suppressed = filter_actionable_drift(drifts)

    assert len(drifts) == 1
    assert drifts[0].score == 0.3333
    assert actionable == drifts
    assert suppressed == {"non_goal": 0, "unrelated": 0}


def test_detect_drift_accepts_spec_bundle() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)
    bundle = SpecBundle(
        prd_path="PRD.md",
        seed_path=None,
        seed_yaml_path=None,
        requirements=[
            _req("Completely unrelated billing feature must ship", line=10),
        ],
    )
    drifts = detect_drift(bundle, diff)
    assert len(drifts) == 1
    assert drifts[0].quote.startswith("Completely unrelated")


def test_drift_items_are_serializable() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)
    reqs = [_req("nonexistent payment integration required", line=7)]
    drifts = detect_drift(reqs, diff)
    assert drifts[0].to_dict()["line"] == 7
    assert drifts[0].to_dict()["type"] == "missing_requirement"


# ---------------------------------------------------------------------------
# filter_actionable_drift
# ---------------------------------------------------------------------------


def _drift(*, kind: str = "acceptance", score: float = 0.5, source: str = "prd") -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=f"{source.upper()}.md",
        section="x",
        kind=kind,
        quote="q",
        line=1,
        score=score,
    )


def test_filter_drops_non_goals() -> None:
    items = [_drift(kind="non_goal", score=0.5), _drift(kind="acceptance", score=0.5)]
    actionable, suppressed = filter_actionable_drift(items)
    assert len(actionable) == 1
    assert actionable[0].kind == "acceptance"
    assert suppressed == {"non_goal": 1, "unrelated": 0}


def test_filter_drops_weak_score_unrelated() -> None:
    items = [_drift(score=0.0), _drift(score=0.2), _drift(score=0.34)]
    actionable, suppressed = filter_actionable_drift(items)
    assert len(actionable) == 1
    assert actionable[0].score == 0.34
    assert suppressed == {"non_goal": 0, "unrelated": 2}


def test_filter_empty_input() -> None:
    actionable, suppressed = filter_actionable_drift([])
    assert actionable == []
    assert suppressed == {"non_goal": 0, "unrelated": 0}


def test_filter_keeps_relevant_partial_match_violations() -> None:
    items = [_drift(score=0.1), _drift(score=0.33), _drift(score=0.34), _drift(score=0.99)]
    actionable, _ = filter_actionable_drift(items)
    assert [d.score for d in actionable] == [0.33, 0.34, 0.99]


def test_filter_floor_is_inclusive() -> None:
    actionable, suppressed = filter_actionable_drift([_drift(score=0.33), _drift(score=0.3299)])
    assert [d.score for d in actionable] == [0.33]
    assert suppressed == {"non_goal": 0, "unrelated": 1}


# ---------------------------------------------------------------------------
# partition_coverage_only_drift — tests/docs-only PRs owe no implementation
# ---------------------------------------------------------------------------

# A pure-test diff whose new test shares one of three salient tokens with a
# requirement ("citation"), landing the match score in the actionable band
# (1/3 = 0.3333: >= ACTIONABLE_SCORE_FLOOR but < the satisfied threshold).
COVERAGE_ONLY_DIFF = """diff --git a/tests/recall.test.ts b/tests/recall.test.ts
new file mode 100644
--- /dev/null
+++ b/tests/recall.test.ts
@@ -0,0 +1,3 @@
+test("recall citation", () => {
+  expect(citation).toBeTruthy();
+});
"""

# Same partial-overlap requirement, but the change is product source, so the
# drift must NOT be suppressed.
SOURCE_PARTIAL_DIFF = """diff --git a/packages/brain/src/recall.ts b/packages/brain/src/recall.ts
new file mode 100644
--- /dev/null
+++ b/packages/brain/src/recall.ts
@@ -0,0 +1,3 @@
+export function buildResult() {
+  return citation;
+}
"""


def test_partition_suppresses_only_implementation_kinds_on_coverage_only() -> None:
    diff = parse_unified_diff(COVERAGE_ONLY_DIFF)
    drifts = [
        _drift(kind="acceptance"),
        _drift(kind="constraint"),
        _drift(kind="intent"),
        _drift(kind="non_goal"),
    ]
    kept, suppressed = partition_coverage_only_drift(drifts, diff)
    assert {d.kind for d in suppressed} == {"acceptance", "constraint", "intent"}
    assert [d.kind for d in kept] == ["non_goal"]


def test_partition_is_noop_on_source_diff() -> None:
    diff = parse_unified_diff(SAMPLE_DIFF)  # touches src/pkg/widget.py
    drifts = [_drift(kind="acceptance"), _drift(kind="constraint")]
    kept, suppressed = partition_coverage_only_drift(drifts, diff)
    assert suppressed == []
    assert kept == drifts


def test_partition_is_noop_on_empty_diff() -> None:
    diff = parse_unified_diff("")
    drifts = [_drift(kind="acceptance")]
    kept, suppressed = partition_coverage_only_drift(drifts, diff)
    assert suppressed == []
    assert kept == drifts


def test_coverage_only_pr_drops_actionable_implementation_drift() -> None:
    """End-to-end: a test-only PR yields zero actionable drift after scope-filter."""
    diff = parse_unified_diff(COVERAGE_ONLY_DIFF)
    # PRD "성공 기준" lines parse as kind="intent" (see spec_parser).
    reqs = [_req("citation accuracy benchmark", kind="intent", line=20)]

    raw = detect_drift(reqs, diff)
    advisory_before, _ = filter_actionable_drift(raw)
    assert len(advisory_before) == 1  # false positive exists pre-fix
    assert advisory_before[0].score == 0.3333

    kept, suppressed = partition_coverage_only_drift(raw, diff)
    advisory_after, _ = filter_actionable_drift(kept)
    assert advisory_after == []  # scope-filter clears the false positive
    assert len(suppressed) == 1
    assert suppressed[0].kind == "intent"


def test_source_pr_preserves_actionable_drift_after_scope_filter() -> None:
    """Regression guard: a real source PR with the same partial match still drifts."""
    diff = parse_unified_diff(SOURCE_PARTIAL_DIFF)
    reqs = [_req("citation accuracy benchmark", kind="intent", line=20)]

    raw = detect_drift(reqs, diff)
    kept, suppressed = partition_coverage_only_drift(raw, diff)
    assert suppressed == []  # source diff → nothing suppressed
    advisory, _ = filter_actionable_drift(kept)
    assert len(advisory) == 1  # genuine source drift preserved


# select_blocking_drift


def test_advisory_drift_is_non_blocking_by_default() -> None:
    advisory = [_drift(score=0.33), _drift(score=0.5)]
    assert select_blocking_drift(advisory) == []


def test_fail_on_advisory_promotes_every_item_to_blocking() -> None:
    advisory = [_drift(score=0.33), _drift(score=0.5)]
    blocking = select_blocking_drift(advisory, fail_on_advisory=True)
    assert blocking == advisory


def test_provider_can_promote_advisory_items_to_blocking() -> None:
    advisory = [_drift(score=0.33), _drift(score=0.5)]

    class Provider:
        def classify_blocking_drift(self, items, *, diff_summary=None):
            assert items == advisory
            assert diff_summary == "scoped diff"
            return [items[1]]

    blocking = select_blocking_drift(
        advisory,
        provider=Provider(),
        diff_summary="scoped diff",
    )

    assert blocking == [advisory[1]]


def test_provider_blocking_decisions_preserve_reason() -> None:
    advisory = [_drift(score=0.33)]

    class Provider:
        def classify_blocking_drift(self, items, *, diff_summary=None):
            return [
                BlockingDriftDecision(
                    drift=items[0],
                    reason="Diff changes the scoped path but omits required behavior.",
                )
            ]

    decisions = select_blocking_drift_decisions(advisory, provider=Provider())

    assert [decision.drift for decision in decisions] == advisory
    assert decisions[0].reason.startswith("Diff changes")
    assert decisions[0].source == "semantic"


def test_provider_absence_or_failure_degrades_to_non_blocking() -> None:
    advisory = [_drift(score=0.33)]

    class FailingProvider:
        def classify_blocking_drift(self, items, *, diff_summary=None):
            raise RuntimeError("provider unavailable")

    assert select_blocking_drift(advisory, provider=object()) == []
    assert select_blocking_drift(advisory, provider=FailingProvider()) == []


def test_select_blocking_empty_input() -> None:
    assert select_blocking_drift([], fail_on_advisory=True) == []
