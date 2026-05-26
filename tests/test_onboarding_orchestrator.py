"""Integration unit tests for onboarding orchestrator (Sub-AC 4)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pr_guard.onboarding_orchestrator import (
    ONBOARDING_TITLE_MARKER,
    OrchestratorResult,
    run_onboarding,
)


class FakeGit:
    def __init__(self):
        self.calls = []

    def create_ref(self, **kwargs):
        self.calls.append(kwargs)
        return {"ref": kwargs["ref"]}


class FakePulls:
    def __init__(self, existing=None, created_number=42):
        self.existing = existing or []
        self.created_number = created_number
        self.create_calls = []
        self.list_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return self.existing

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return {"number": self.created_number}


class FakeOctokit:
    def __init__(self, existing=None, created_number=42):
        self.git = FakeGit()
        self.pulls = FakePulls(existing=existing, created_number=created_number)


def test_creates_pr_when_specs_missing(tmp_path: Path):
    octo = FakeOctokit(created_number=101)
    result = run_onboarding(
        octo,
        repo_root=tmp_path,
        owner="darbykim",
        repo="foo",
        full_name="darbykim/foo",
        default_branch="main",
        base_sha="deadbeef",
    )
    assert result == OrchestratorResult(status="created", pr_number=101)
    # Branch created from base_sha
    assert octo.git.calls and octo.git.calls[0]["sha"] == "deadbeef"
    assert octo.git.calls[0]["ref"].startswith("refs/heads/")
    # PR created with title containing marker and rendered body
    assert len(octo.pulls.create_calls) == 1
    call = octo.pulls.create_calls[0]
    assert ONBOARDING_TITLE_MARKER in call["title"]
    assert "darbykim/foo" in call["title"]
    assert "ooo interview" in call["body"]


def test_skips_when_specs_present(tmp_path: Path):
    (tmp_path / "PRD.md").write_text("p")
    (tmp_path / "SEED.md").write_text("s")
    octo = FakeOctokit()
    result = run_onboarding(
        octo,
        repo_root=tmp_path,
        owner="o",
        repo="r",
        full_name="o/r",
        base_sha="abc",
    )
    assert result.status == "skipped_has_specs"
    assert result.pr_number is None
    # No branch, no PR, no list call needed
    assert octo.git.calls == []
    assert octo.pulls.create_calls == []


def test_skips_when_existing_onboarding_pr(tmp_path: Path):
    existing = [
        {"number": 7, "title": "unrelated PR"},
        {"number": 9, "title": f"{ONBOARDING_TITLE_MARKER} for darbykim/foo"},
    ]
    octo = FakeOctokit(existing=existing)
    result = run_onboarding(
        octo,
        repo_root=tmp_path,
        owner="darbykim",
        repo="foo",
        full_name="darbykim/foo",
        base_sha="abc",
    )
    assert result.status == "skipped_existing"
    assert result.pr_number == 9
    # No branch creation, no PR create
    assert octo.git.calls == []
    assert octo.pulls.create_calls == []


def test_only_missing_prd_renders_only_prd(tmp_path: Path):
    (tmp_path / "SEED.md").write_text("s")
    octo = FakeOctokit()
    run_onboarding(
        octo,
        repo_root=tmp_path,
        owner="o",
        repo="r",
        full_name="o/r",
        base_sha="abc",
    )
    body = octo.pulls.create_calls[0]["body"]
    missing_section = body.split("## Missing files")[1].split("##")[0]
    assert "`PRD.md`" in missing_section
    assert "`SEED.md`" not in missing_section


def test_supports_attribute_style_pr_list(tmp_path: Path):
    existing = [SimpleNamespace(number=11, title=f"{ONBOARDING_TITLE_MARKER} x")]
    octo = FakeOctokit(existing=existing)
    result = run_onboarding(
        octo,
        repo_root=tmp_path,
        owner="o",
        repo="r",
        full_name="o/r",
        base_sha="abc",
    )
    assert result.status == "skipped_existing"
    assert result.pr_number == 11
