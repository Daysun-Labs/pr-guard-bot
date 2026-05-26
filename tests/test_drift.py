"""Sub-AC 2: drift detection tests.

Covers both the drift ≥1 case (PR diff misses a PRD/SEED requirement)
and the drift == 0 case (PR diff covers every requirement).
"""

from __future__ import annotations

from pr_guard.diff_extractor import parse_unified_diff
from pr_guard.drift import DriftItem, detect_drift
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
