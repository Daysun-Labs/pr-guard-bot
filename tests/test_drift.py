"""Sub-AC 2: drift detection tests.

Covers both the drift ≥1 case (PR diff misses a PRD/SEED requirement)
and the drift == 0 case (PR diff covers every requirement).
"""

from __future__ import annotations

from pr_guard.diff_extractor import parse_unified_diff
from pr_guard.drift import DriftItem, detect_drift, filter_actionable_drift
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
