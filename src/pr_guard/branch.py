"""Branch creation helpers (Sub-AC 2).

`create_branch` (a.k.a. createBranch) creates a new git ref on a repo
starting from a given base SHA. It is written to work with any
octokit-style client exposing `client.git.create_ref(owner, repo, ref, sha)`.
"""

from __future__ import annotations

from typing import Any


def create_branch(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    branch: str,
    base_sha: str,
) -> Any:
    """Create a new branch `branch` pointing at `base_sha`.

    Calls `octokit.git.create_ref` with the canonical `refs/heads/<branch>`
    ref name. Returns whatever the underlying client returns.

    Args:
        octokit: object exposing `.git.create_ref(owner, repo, ref, sha)`.
        owner: repository owner / org.
        repo: repository name.
        branch: short branch name (no `refs/heads/` prefix).
        base_sha: commit SHA the new branch should point at.

    Raises:
        ValueError: if `branch` or `base_sha` is empty / falsy.
    """
    if not branch:
        raise ValueError("branch must be a non-empty string")
    if not base_sha:
        raise ValueError("base_sha must be a non-empty string")
    if branch.startswith("refs/"):
        raise ValueError("branch must be a short name, not a full ref")

    ref = f"refs/heads/{branch}"
    return octokit.git.create_ref(
        owner=owner,
        repo=repo,
        ref=ref,
        sha=base_sha,
    )
