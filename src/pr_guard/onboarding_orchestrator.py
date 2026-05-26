"""Onboarding PR orchestrator (Sub-AC 4).

Wires detector -> template -> branch/PR client into a single entry point
that opens an onboarding PR for repos missing PRD/SEED, while preventing
duplicate PRs by checking for existing open onboarding PRs.

Pure-ish: all GitHub I/O is delegated to the injected `octokit`-style client.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .branch import create_branch
from .detector import detect_spec_files
from .onboarding_pr import RepoMetadata, render_onboarding_pr
from .pull_request import open_pull_request

ONBOARDING_TITLE_MARKER = "[pr-guard] Bootstrap PRD/SEED"
DEFAULT_BRANCH_NAME = "pr-guard/onboarding"


@dataclass(frozen=True)
class OrchestratorResult:
    status: str  # "created" | "skipped_existing" | "skipped_has_specs"
    pr_number: Optional[int] = None
    reason: Optional[str] = None


def _missing_files(presence: dict[str, bool]) -> tuple[str, ...]:
    out: list[str] = []
    if not presence.get("prd"):
        out.append("PRD.md")
    if not presence.get("seed"):
        out.append("SEED.md")
    return tuple(out)


def _find_existing_onboarding_pr(
    octokit: Any, owner: str, repo: str
) -> Optional[int]:
    """Return PR number of an existing open onboarding PR, else None."""
    prs = octokit.pulls.list(owner=owner, repo=repo, state="open")
    for pr in prs or []:
        title = pr.get("title") if isinstance(pr, dict) else getattr(pr, "title", "")
        if title and ONBOARDING_TITLE_MARKER in title:
            num = pr.get("number") if isinstance(pr, dict) else getattr(pr, "number", None)
            if num is not None:
                return int(num)
    return None


def run_onboarding(
    octokit: Any,
    *,
    repo_root: str | Path,
    owner: str,
    repo: str,
    full_name: str,
    default_branch: str = "main",
    base_sha: str,
    branch_name: str = DEFAULT_BRANCH_NAME,
) -> OrchestratorResult:
    """Orchestrate the onboarding flow for a repo.

    Steps:
      1. Detect whether PRD/SEED exist locally; if both present, skip.
      2. Check for an existing open onboarding PR; if found, skip (no dup).
      3. Create a branch, render template, open PR. Return PR number.
    """
    presence = detect_spec_files(repo_root)
    missing = _missing_files(presence)
    if not missing:
        return OrchestratorResult(status="skipped_has_specs", reason="PRD and SEED already present")

    existing = _find_existing_onboarding_pr(octokit, owner, repo)
    if existing is not None:
        return OrchestratorResult(
            status="skipped_existing",
            pr_number=existing,
            reason="existing onboarding PR found",
        )

    create_branch(
        octokit,
        owner=owner,
        repo=repo,
        branch=branch_name,
        base_sha=base_sha,
    )

    meta = RepoMetadata(
        full_name=full_name,
        default_branch=default_branch,
        missing=missing,
    )
    rendered = render_onboarding_pr(meta)
    pr_number = open_pull_request(
        octokit,
        owner=owner,
        repo=repo,
        head=branch_name,
        base=default_branch,
        title=rendered["title"],
        body=rendered["body"],
    )
    return OrchestratorResult(status="created", pr_number=pr_number)
