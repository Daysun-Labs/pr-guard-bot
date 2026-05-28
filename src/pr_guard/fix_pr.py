"""Orchestrate fix-PR creation: branch → commit → PR.

Glues together branch creation, commit_file_change, and pull_request.open_pull_request
for a single drift → fix-PR transformation.

Routing:
  drift.source == "prd"  → kind = "code-fix"   (Claude usually creates docs proposal)
  drift.source == "seed" → kind = "seed-fix"   (SEED.md direct update)
"""
from __future__ import annotations

from typing import Any

from .branch import branch_name_for_drift, create_branch, create_branch_for_drift
from .commit import FileChange, commit_file_change
from .drift import DriftItem
from .pull_request import open_pull_request


FIX_KIND_BY_SOURCE = {"prd": "code-fix", "seed": "seed-fix"}


def create_fix_pr(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    drift: DriftItem,
    change: FileChange,
    rationale: str,
    base_sha: str,
    default_branch: str,
    source_pr_number: int,
    draft: bool = True,
) -> tuple[str, int]:
    """Create one fix-PR for one drift item.

    Returns ``(branch_name, new_pr_number)``.

    Always opens as draft by default — these PRs are bot-generated and
    should be reviewed before any merge.
    """
    kind = FIX_KIND_BY_SOURCE.get(drift.source, "fix")
    prefix = f"pr-guard/{kind}"
    branch, _ = create_branch_for_drift(
        octokit,
        owner=owner,
        repo=repo,
        drift=drift,
        base_sha=base_sha,
        prefix=prefix,
    )
    commit_file_change(
        octokit,
        owner=owner,
        repo=repo,
        branch=branch,
        change=change,
    )
    title = _truncate(f"[pr-guard:{kind}] {drift.quote}", 72)
    body = _render_body(drift, rationale, source_pr_number=source_pr_number, kind=kind)
    pr_number = open_pull_request(
        octokit,
        owner=owner,
        repo=repo,
        head=branch,
        base=default_branch,
        title=title,
        body=body,
        draft=draft,
    )
    return branch, pr_number


def create_or_reuse_fix_pr(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    drift: DriftItem,
    change: FileChange,
    rationale: str,
    base_sha: str,
    default_branch: str,
    source_pr_number: int,
    draft: bool = True,
    max_branch_attempts: int = 5,
) -> dict[str, Any]:
    """Idempotently create or reuse a fix PR for one drift item.

    The primary branch name remains deterministic for the drift. If an open PR
    already exists for that branch, the PR is reused and no new commit is made.
    If the branch exists without an open PR (closed PR or stale branch), create a
    bounded suffix branch instead of surfacing GitHub's 422 as a hard failure.
    """
    kind = FIX_KIND_BY_SOURCE.get(drift.source, "fix")
    prefix = f"pr-guard/{kind}"
    primary_branch = branch_name_for_drift(drift, prefix=prefix)
    title = _truncate(f"[pr-guard:{kind}] {drift.quote}", 72)
    body = _render_body(drift, rationale, source_pr_number=source_pr_number, kind=kind)

    existing = _find_open_pr_for_branch_family(
        octokit,
        owner=owner,
        repo=repo,
        primary_branch=primary_branch,
        default_branch=default_branch,
    )
    if existing is not None:
        pr_number = _pr_number(existing)
        existing_branch = _head_ref(existing) or primary_branch
        return _result(
            drift=drift,
            status="reused",
            branch=existing_branch,
            pr_number=pr_number,
            reason=(
                f"existing open PR #{pr_number} already uses `{existing_branch}`; "
                "reused instead of creating a duplicate fix PR"
            ),
        )

    branch, branch_reason = _create_unique_branch(
        octokit,
        owner=owner,
        repo=repo,
        primary_branch=primary_branch,
        base_sha=base_sha,
        max_attempts=max_branch_attempts,
    )
    if branch is None:
        return _result(
            drift=drift,
            status="skipped",
            branch=primary_branch,
            pr_number=None,
            reason=branch_reason,
        )

    commit_file_change(
        octokit,
        owner=owner,
        repo=repo,
        branch=branch,
        change=change,
    )
    try:
        pr_number = open_pull_request(
            octokit,
            owner=owner,
            repo=repo,
            head=branch,
            base=default_branch,
            title=title,
            body=body,
            draft=draft,
        )
    except Exception as exc:
        if _status_code(exc) != 422:
            raise
        existing = _find_open_pr_for_branch(
            octokit,
            owner=owner,
            repo=repo,
            branch=branch,
            default_branch=default_branch,
        )
        if existing is not None:
            pr_number = _pr_number(existing)
            return _result(
                drift=drift,
                status="reused",
                branch=branch,
                pr_number=pr_number,
                reason=(
                    f"GitHub rejected PR creation for `{branch}` with 422, "
                    f"but open PR #{pr_number} already exists; reused it"
                ),
            )
        return _result(
            drift=drift,
            status="skipped",
            branch=branch,
            pr_number=None,
            reason=(
                f"GitHub rejected PR creation for `{branch}` with 422 and no "
                "open PR was discoverable; skipped duplicate fix PR creation"
            ),
        )

    return _result(
        drift=drift,
        status="created",
        branch=branch,
        pr_number=pr_number,
        reason=branch_reason,
    )


def _create_unique_branch(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    primary_branch: str,
    base_sha: str,
    max_attempts: int,
) -> tuple[str | None, str]:
    max_attempts = max(1, max_attempts)
    for attempt in range(1, max_attempts + 1):
        branch = primary_branch if attempt == 1 else f"{primary_branch}-{attempt}"
        try:
            create_branch(
                octokit,
                owner=owner,
                repo=repo,
                branch=branch,
                base_sha=base_sha,
            )
            if branch == primary_branch:
                return branch, f"created new fix PR branch `{branch}`"
            return (
                branch,
                f"primary branch `{primary_branch}` already existed without an "
                f"open PR; created suffix branch `{branch}`",
            )
        except Exception as exc:
            if _status_code(exc) != 422:
                raise
            continue
    return (
        None,
        f"could not create a unique branch after {max_attempts} attempt(s); "
        f"`{primary_branch}` and suffix branches collided without an open PR",
    )


def _find_open_pr_for_branch(
    octokit: Any, *, owner: str, repo: str, branch: str, default_branch: str
) -> dict[str, Any] | Any | None:
    return _find_open_pr(
        octokit,
        owner=owner,
        repo=repo,
        default_branch=default_branch,
        predicate=lambda ref: ref == branch,
    )


def _find_open_pr_for_branch_family(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    primary_branch: str,
    default_branch: str,
) -> dict[str, Any] | Any | None:
    return _find_open_pr(
        octokit,
        owner=owner,
        repo=repo,
        default_branch=default_branch,
        predicate=lambda ref: _is_branch_family_member(ref, primary_branch),
    )


def _find_open_pr(
    octokit: Any, *, owner: str, repo: str, default_branch: str, predicate: Any
) -> dict[str, Any] | Any | None:
    pulls = getattr(octokit, "pulls", None)
    list_pulls = getattr(pulls, "list", None)
    if list_pulls is None:
        return None
    prs = list_pulls(owner=owner, repo=repo, state="open")
    for pr in prs or []:
        ref = _head_ref(pr)
        if (
            ref is not None
            and predicate(ref)
            and _matches_same_repo_and_base(
                pr, owner=owner, repo=repo, default_branch=default_branch
            )
        ):
            return pr
    return None


def _is_branch_family_member(ref: str, primary_branch: str) -> bool:
    if ref == primary_branch:
        return True
    prefix = f"{primary_branch}-"
    if not ref.startswith(prefix):
        return False
    return ref[len(prefix) :].isdigit()


def _head_ref(pr: dict[str, Any] | Any) -> str | None:
    if isinstance(pr, dict):
        head = pr.get("head")
        if isinstance(head, dict):
            ref = head.get("ref")
            if ref:
                return str(ref)
            label = head.get("label")
            if isinstance(label, str) and ":" in label:
                return label.split(":", 1)[1]
        ref = pr.get("head_ref") or pr.get("headRefName")
        return str(ref) if ref else None

    head = getattr(pr, "head", None)
    ref = getattr(head, "ref", None)
    if ref:
        return str(ref)
    ref = getattr(pr, "head_ref", None) or getattr(pr, "headRefName", None)
    return str(ref) if ref else None


def _matches_same_repo_and_base(
    pr: dict[str, Any] | Any, *, owner: str, repo: str, default_branch: str
) -> bool:
    expected_repo = f"{owner}/{repo}".lower()
    head_repo = _head_repo_full_name(pr)
    base_ref = _base_ref(pr)
    return head_repo == expected_repo and base_ref == default_branch


def _head_repo_full_name(pr: dict[str, Any] | Any) -> str | None:
    repo_obj: Any | None = None
    if isinstance(pr, dict):
        head = pr.get("head")
        if isinstance(head, dict):
            repo_obj = head.get("repo")
    else:
        head = getattr(pr, "head", None)
        repo_obj = getattr(head, "repo", None) if head is not None else None

    if repo_obj is None:
        return None
    if isinstance(repo_obj, dict):
        full_name = repo_obj.get("full_name") or repo_obj.get("fullName")
        if full_name:
            return str(full_name).lower()
        owner_obj = repo_obj.get("owner")
        owner_login = owner_obj.get("login") if isinstance(owner_obj, dict) else None
        name = repo_obj.get("name")
        if owner_login and name:
            return f"{owner_login}/{name}".lower()
        return None

    full_name = getattr(repo_obj, "full_name", None) or getattr(repo_obj, "fullName", None)
    if full_name:
        return str(full_name).lower()
    owner_obj = getattr(repo_obj, "owner", None)
    owner_login = getattr(owner_obj, "login", None) if owner_obj is not None else None
    name = getattr(repo_obj, "name", None)
    if owner_login and name:
        return f"{owner_login}/{name}".lower()
    return None


def _base_ref(pr: dict[str, Any] | Any) -> str | None:
    if isinstance(pr, dict):
        base = pr.get("base")
        if isinstance(base, dict):
            ref = base.get("ref")
            if ref:
                return str(ref)
        ref = pr.get("base_ref") or pr.get("baseRefName")
        return str(ref) if ref else None

    base = getattr(pr, "base", None)
    ref = getattr(base, "ref", None)
    if ref:
        return str(ref)
    ref = getattr(pr, "base_ref", None) or getattr(pr, "baseRefName", None)
    return str(ref) if ref else None


def _pr_number(pr: dict[str, Any] | Any) -> int:
    number = pr.get("number") if isinstance(pr, dict) else getattr(pr, "number", None)
    if number is None:
        raise ValueError("pull request object missing 'number'")
    return int(number)


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        if status is not None:
            return int(status)
    status = getattr(exc, "status_code", None)
    return int(status) if status is not None else None


def _result(
    *,
    drift: DriftItem,
    status: str,
    branch: str,
    pr_number: int | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "drift": drift,
        "status": status,
        "branch": branch,
        "pr_number": pr_number,
        "reason": reason,
    }


def _truncate(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _render_body(
    drift: DriftItem,
    rationale: str,
    *,
    source_pr_number: int,
    kind: str,
) -> str:
    return (
        f"Auto-generated **{kind}** for drift detected in #{source_pr_number}.\n"
        f"\n"
        f"## Source\n"
        f"- file: `{drift.source_file}:{drift.line}`\n"
        f"- spec: `{drift.source.upper()}` · severity `{drift.severity}` · "
        f"match score `{drift.score:.2f}`\n"
        f"\n"
        f"## Requirement (verbatim)\n"
        f"> {drift.quote}\n"
        f"\n"
        f"## Rationale (from pr-guard)\n"
        f"{rationale}\n"
        f"\n"
        f"---\n"
        f"_This PR was auto-generated by pr-guard-bot. Review carefully "
        f"before merging — bot-generated patches are starting points, not "
        f"finished work._"
    )
