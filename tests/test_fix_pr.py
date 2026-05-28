"""Unit tests for fix_pr — octokit is stubbed."""
from __future__ import annotations

from typing import Any

from pr_guard.branch import branch_name_for_drift
from pr_guard.commit import FileChange
from pr_guard.drift import DriftItem
from pr_guard.fix_pr import create_fix_pr, create_or_reuse_fix_pr


# ──────────────────────────────────────────────────────────────────────────
# Fake octokit
# ──────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"GitHub API {status_code}")
        self.response = _FakeResponse(status_code)


class _FakeGit:
    def __init__(self, *, fail_refs: set[str] | None = None, fail_all_refs: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail_refs = fail_refs or set()
        self.fail_all_refs = fail_all_refs

    def create_ref(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.fail_all_refs or kwargs["ref"] in self.fail_refs:
            raise _StatusError(422)
        return {"ref": kwargs["ref"], "object": {"sha": kwargs["sha"]}}


class _FakeRepos:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_or_update_file_contents(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"commit": {"sha": "abc1234"}}


class _FakePulls:
    def __init__(
        self,
        next_number: int = 99,
        *,
        open_prs: list[dict] | None = None,
        open_prs_after_create_error: list[dict] | None = None,
        create_error_status: int | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.list_calls: list[dict] = []
        self._next = next_number
        self._open_prs = open_prs or []
        self._open_prs_after_create_error = open_prs_after_create_error
        self._create_error_status = create_error_status
        self._create_failed = False

    def create(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self._create_error_status is not None:
            self._create_failed = True
            raise _StatusError(self._create_error_status)
        return {"number": self._next}

    def list(self, **kwargs: Any) -> list[dict]:
        self.list_calls.append(kwargs)
        if kwargs.get("state") == "open":
            if self._create_failed and self._open_prs_after_create_error is not None:
                return self._open_prs_after_create_error
            return self._open_prs
        return []


class FakeOctokit:
    def __init__(
        self,
        pr_number: int = 99,
        *,
        open_prs: list[dict] | None = None,
        open_prs_after_create_error: list[dict] | None = None,
        fail_refs: set[str] | None = None,
        fail_all_refs: bool = False,
        create_pr_error_status: int | None = None,
    ) -> None:
        self.git = _FakeGit(fail_refs=fail_refs, fail_all_refs=fail_all_refs)
        self.repos = _FakeRepos()
        self.pulls = _FakePulls(
            next_number=pr_number,
            open_prs=open_prs,
            open_prs_after_create_error=open_prs_after_create_error,
            create_error_status=create_pr_error_status,
        )


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


def test_reuses_existing_open_fix_pr_without_new_branch_or_commit() -> None:
    drift = _drift(source="prd")
    branch = branch_name_for_drift(drift, prefix="pr-guard/code-fix")
    octo = FakeOctokit(
        open_prs=[
            {
                "number": 44,
                "head": {"ref": branch, "repo": {"full_name": "me/proj"}},
                "base": {"ref": "main"},
            }
        ]
    )

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="docs/proposal.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "reused"
    assert result["pr_number"] == 44
    assert result["branch"] == branch
    assert "existing open PR" in result["reason"]
    assert octo.git.calls == []
    assert octo.repos.calls == []
    assert octo.pulls.calls == []


def test_reuses_existing_open_suffix_fix_pr_for_same_drift() -> None:
    drift = _drift(source="seed")
    primary = branch_name_for_drift(drift, prefix="pr-guard/seed-fix")
    suffix_branch = f"{primary}-2"
    octo = FakeOctokit(
        open_prs=[
            {
                "number": 45,
                "head": {"ref": suffix_branch, "repo": {"full_name": "me/proj"}},
                "base": {"ref": "main"},
            }
        ]
    )

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "reused"
    assert result["pr_number"] == 45
    assert result["branch"] == suffix_branch
    assert octo.git.calls == []
    assert octo.repos.calls == []
    assert octo.pulls.calls == []


def test_does_not_reuse_open_pr_from_fork_with_same_branch_ref() -> None:
    drift = _drift(source="seed")
    branch = branch_name_for_drift(drift, prefix="pr-guard/seed-fix")
    octo = FakeOctokit(
        pr_number=102,
        open_prs=[
            {
                "number": 46,
                "head": {"ref": branch, "repo": {"full_name": "evil/proj"}},
                "base": {"ref": "main"},
            }
        ],
    )

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "created"
    assert result["pr_number"] == 102
    assert result["branch"] == branch
    assert octo.git.calls[0]["ref"] == f"refs/heads/{branch}"
    assert octo.repos.calls[0]["branch"] == branch
    assert octo.pulls.calls[0]["head"] == branch


def test_does_not_reuse_open_pr_targeting_other_base() -> None:
    drift = _drift(source="seed")
    branch = branch_name_for_drift(drift, prefix="pr-guard/seed-fix")
    octo = FakeOctokit(
        pr_number=103,
        open_prs=[
            {
                "number": 47,
                "head": {"ref": branch, "repo": {"full_name": "me/proj"}},
                "base": {"ref": "develop"},
            }
        ],
    )

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "created"
    assert result["pr_number"] == 103
    assert result["branch"] == branch
    assert octo.git.calls[0]["ref"] == f"refs/heads/{branch}"
    assert octo.repos.calls[0]["branch"] == branch
    assert octo.pulls.calls[0]["head"] == branch


def test_reuses_post_create_422_only_for_same_repo_and_base() -> None:
    drift = _drift(source="prd")
    branch = branch_name_for_drift(drift, prefix="pr-guard/code-fix")
    octo = FakeOctokit(
        create_pr_error_status=422,
        open_prs=[
            {
                "number": 48,
                "head": {"ref": branch, "repo": {"full_name": "fork/proj"}},
                "base": {"ref": "main"},
            }
        ],
        open_prs_after_create_error=[
            {
                "number": 48,
                "head": {"ref": branch, "repo": {"full_name": "fork/proj"}},
                "base": {"ref": "main"},
            },
            {
                "number": 49,
                "head": {"ref": branch, "repo": {"full_name": "me/proj"}},
                "base": {"ref": "main"},
            },
        ],
    )

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="docs/proposal.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "reused"
    assert result["pr_number"] == 49
    assert result["branch"] == branch
    assert "422" in result["reason"]
    assert octo.repos.calls[0]["branch"] == branch
    assert octo.pulls.calls[0]["head"] == branch


def test_suffixes_branch_when_primary_branch_exists_without_open_pr() -> None:
    drift = _drift(source="seed")
    primary = branch_name_for_drift(drift, prefix="pr-guard/seed-fix")
    octo = FakeOctokit(pr_number=101, fail_refs={f"refs/heads/{primary}"})

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
    )

    assert result["status"] == "created"
    assert result["pr_number"] == 101
    assert result["branch"] == f"{primary}-2"
    assert "suffix branch" in result["reason"]
    assert [c["ref"] for c in octo.git.calls] == [
        f"refs/heads/{primary}",
        f"refs/heads/{primary}-2",
    ]
    assert octo.repos.calls[0]["branch"] == f"{primary}-2"
    assert octo.pulls.calls[0]["head"] == f"{primary}-2"


def test_skips_when_no_unique_suffix_branch_can_be_created() -> None:
    drift = _drift(source="seed")
    octo = FakeOctokit(fail_all_refs=True)

    result = create_or_reuse_fix_pr(
        octo,
        owner="me",
        repo="proj",
        drift=drift,
        change=FileChange(path="SEED.md", content="x", message="m"),
        rationale="r",
        base_sha="cafe",
        default_branch="main",
        source_pr_number=77,
        max_branch_attempts=2,
    )

    assert result["status"] == "skipped"
    assert result["pr_number"] is None
    assert "unique branch" in result["reason"]
    assert len(octo.git.calls) == 2
    assert octo.repos.calls == []
    assert octo.pulls.calls == []
