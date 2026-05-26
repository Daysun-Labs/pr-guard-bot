"""Unit tests for fix_pr — octokit is stubbed."""
from __future__ import annotations

from typing import Any

from pr_guard.commit import FileChange
from pr_guard.drift import DriftItem
from pr_guard.fix_pr import create_fix_pr


# ──────────────────────────────────────────────────────────────────────────
# Fake octokit
# ──────────────────────────────────────────────────────────────────────────


class _FakeGit:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_ref(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"ref": kwargs["ref"], "object": {"sha": kwargs["sha"]}}


class _FakeRepos:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_or_update_file_contents(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"commit": {"sha": "abc1234"}}


class _FakePulls:
    def __init__(self, next_number: int = 99) -> None:
        self.calls: list[dict] = []
        self._next = next_number

    def create(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"number": self._next}


class FakeOctokit:
    def __init__(self, pr_number: int = 99) -> None:
        self.git = _FakeGit()
        self.repos = _FakeRepos()
        self.pulls = _FakePulls(next_number=pr_number)


def _drift(*, source: str = "seed", quote: str = "PR comment within 5 min") -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=f"{source.upper()}.md",
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=42,
        score=0.5,
    )


# ──────────────────────────────────────────────────────────────────────────
# create_fix_pr
# ──────────────────────────────────────────────────────────────────────────


def test_seed_fix_routes_to_seed_fix_branch_prefix() -> None:
    octo = FakeOctokit(pr_number=123)
    branch, pr = create_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=_drift(source="seed"),
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="deadbeef",
        default_branch="main",
        source_pr_number=42,
    )
    assert pr == 123
    assert branch.startswith("pr-guard/seed-fix/")
    # ref created with the same branch
    assert octo.git.calls[0]["ref"] == f"refs/heads/{branch}"
    assert octo.git.calls[0]["sha"] == "deadbeef"


def test_prd_drift_routes_to_code_fix_branch_prefix() -> None:
    octo = FakeOctokit()
    branch, _ = create_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=_drift(source="prd"),
        change=FileChange(path="docs/x.md", content="y", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=1,
    )
    assert branch.startswith("pr-guard/code-fix/")


def test_pr_opened_as_draft_with_mention() -> None:
    octo = FakeOctokit()
    create_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=_drift(),
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )
    call = octo.pulls.calls[0]
    assert call["draft"] is True
    assert "#77" in call["body"]
    assert call["title"].startswith("[pr-guard:seed-fix]")


def test_pr_title_is_truncated_for_long_quotes() -> None:
    octo = FakeOctokit()
    long_quote = "x" * 200
    create_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=_drift(quote=long_quote),
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=1,
    )
    title = octo.pulls.calls[0]["title"]
    assert len(title) <= 72
    assert title.endswith("…")


def test_commit_uses_returned_branch_name() -> None:
    octo = FakeOctokit()
    branch, _ = create_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=_drift(),
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=1,
    )
    assert octo.repos.calls[0]["branch"] == branch
    assert octo.repos.calls[0]["path"] == "SEED.md"
