"""Unit tests for onboarding PR template renderer."""
from __future__ import annotations

from pr_guard.onboarding_pr import (
    RepoMetadata,
    render_onboarding_pr,
    render_onboarding_pr_body,
    render_onboarding_pr_title,
)


def test_title_includes_repo_full_name_and_command():
    repo = RepoMetadata(full_name="darbykim/foo")
    title = render_onboarding_pr_title(repo)
    assert "darbykim/foo" in title
    assert "ooo interview" in title


def test_body_includes_missing_files_and_default_branch():
    repo = RepoMetadata(
        full_name="darbykim/bar",
        default_branch="trunk",
        missing=("PRD.md", "SEED.md"),
    )
    body = render_onboarding_pr_body(repo)
    assert "darbykim/bar" in body
    assert "`PRD.md`" in body
    assert "`SEED.md`" in body
    assert "trunk" in body
    assert "ooo interview" in body
    assert "ooo seed" in body


def test_body_handles_single_missing_file():
    repo = RepoMetadata(full_name="x/y", missing=("SEED.md",))
    body = render_onboarding_pr_body(repo)
    # "Missing files" 섹션에 SEED.md만 표시돼야 함
    missing_section = body.split("## Missing files")[1].split("##")[0]
    assert "`SEED.md`" in missing_section
    assert "`PRD.md`" not in missing_section


def test_body_is_pure_deterministic():
    repo = RepoMetadata(full_name="x/y")
    assert render_onboarding_pr_body(repo) == render_onboarding_pr_body(repo)


def test_render_onboarding_pr_returns_title_and_body():
    repo = RepoMetadata(full_name="darbykim/baz")
    out = render_onboarding_pr(repo)
    assert set(out.keys()) == {"title", "body"}
    assert "darbykim/baz" in out["title"]
    assert "darbykim/baz" in out["body"]


def test_default_missing_is_prd_and_seed():
    repo = RepoMetadata(full_name="a/b")
    body = render_onboarding_pr_body(repo)
    assert "`PRD.md`" in body
    assert "`SEED.md`" in body
