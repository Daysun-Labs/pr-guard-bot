"""Unit tests for the PRD/SEED parser module (Sub-AC 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pr_guard.spec_parser import (
    Requirement,
    SpecBundle,
    parse_prd_markdown,
    parse_repo,
    parse_seed_markdown,
    parse_seed_yaml,
)


PRD_SAMPLE = """\
# PRD — sample

## 한 줄 정의

본인용 봇.

## 성공 기준

| # | 기준 | 측정 방법 |
|---|---|---|
| 1 | 봇이 PR에 5분 내 응답 | Slack 알림 시각 |
| 2 | drift 분류 정확도 ≥90% | 30개 시나리오 |

## 비-목표

- 자동 머지
- Multi-tenant
"""


SEED_SAMPLE = """\
# SEED — sample

## 핵심 제약

- Python >= 3.12
- GitHub Actions only

## 인수 조건 (DoD)

1. `pull_request: opened` 이벤트에 트리거
2. PRD/SEED 존재 리포: 5분 내 코멘트

```python
# code block should not be parsed as requirement
- not a bullet
```
"""


SEED_YAML_SAMPLE = """\
goal: |
  multi-line goal text
constraints:
  - single user only
  - "GitHub Actions only"
acceptance_criteria:
  - PR event triggers within 5 min
  - drift detection produces fix PR
project_type: greenfield
"""


def test_parse_prd_markdown_extracts_table_rows_and_bullets():
    reqs = parse_prd_markdown(PRD_SAMPLE)
    texts = [r.text for r in reqs]
    assert any("5분 내 응답" in t for t in texts)
    assert any("drift 분류" in t for t in texts)
    assert any("자동 머지" in t for t in texts)
    # All from PRD
    assert all(r.source == "prd" for r in reqs)
    # Non-goal classification
    non_goals = [r for r in reqs if r.kind == "non_goal"]
    assert len(non_goals) >= 1


def test_parse_seed_markdown_handles_numbered_and_bullets_and_skips_code():
    reqs = parse_seed_markdown(SEED_SAMPLE)
    texts = [r.text for r in reqs]
    assert any("Python >= 3.12" in t for t in texts)
    assert any("pull_request: opened" in t for t in texts)
    # Code-block content must not appear
    assert not any("not a bullet" in t for t in texts)
    # Kinds present
    kinds = {r.kind for r in reqs}
    assert "constraint" in kinds
    assert "acceptance" in kinds


def test_parse_seed_yaml_extracts_acceptance_and_constraints():
    reqs = parse_seed_yaml(SEED_YAML_SAMPLE)
    texts = [r.text for r in reqs]
    assert "single user only" in texts
    assert "GitHub Actions only" in texts  # quotes stripped
    assert "PR event triggers within 5 min" in texts
    # goal is not extracted (multiline scalar)
    assert not any("multi-line goal text" in t for t in texts)
    # Kind mapping
    for r in reqs:
        if r.section == "constraints":
            assert r.kind == "constraint"
        if r.section == "acceptance_criteria":
            assert r.kind == "acceptance"


def test_parse_repo_combines_files_and_reports_missing(tmp_path: Path):
    (tmp_path / "PRD.md").write_text(PRD_SAMPLE, encoding="utf-8")
    (tmp_path / "SEED.yaml").write_text(SEED_YAML_SAMPLE, encoding="utf-8")
    bundle = parse_repo(tmp_path)
    assert isinstance(bundle, SpecBundle)
    assert bundle.prd_path == "PRD.md"
    assert bundle.seed_yaml_path == "SEED.yaml"
    assert bundle.seed_path is None
    assert "SEED.md" in bundle.missing
    assert len(bundle.requirements) >= 4
    d = bundle.to_dict()
    assert d["requirements"] and "text" in d["requirements"][0]


def test_parse_repo_on_empty_dir_reports_all_missing(tmp_path: Path):
    bundle = parse_repo(tmp_path)
    assert bundle.requirements == []
    assert set(bundle.missing) == {"PRD.md", "SEED.md"}


def test_requirement_has_provenance_fields():
    reqs = parse_prd_markdown(PRD_SAMPLE, source_file="PRD.md")
    r = reqs[0]
    assert isinstance(r, Requirement)
    assert r.source_file == "PRD.md"
    assert r.line > 0
    assert r.section
