"""Branch creation helpers (Sub-AC 2).

`create_branch` (a.k.a. createBranch) creates a new git ref on a repo
starting from a given base SHA. It is written to work with any
octokit-style client exposing `client.git.create_ref(owner, repo, ref, sha)`.

Sub-AC 2.5.1 adds ``branch_name_for_drift`` — a pure helper that derives
a stable, unique branch name from a ``DriftItem`` so fix-PR branches do
not collide when multiple drifts are remediated in the same repo — and
``create_branch_for_drift`` which composes the two: derive a branch name
from a drift and create that ref via the octokit client.
"""

from __future__ import annotations

import hashlib
import re
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


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, *, max_len: int = 32) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def branch_name_for_drift(drift: Any, *, prefix: str = "pr-guard/fix") -> str:
    """Derive a unique, deterministic branch name from a drift item.

    The name is unique per (source_file, line, quote) tuple by appending
    a short hash digest. Accepts a ``DriftItem`` or any object/dict with
    ``source``, ``source_file``, ``line`` and ``quote`` fields.
    """

    def _get(key: str, default: str = "") -> Any:
        if isinstance(drift, dict):
            return drift.get(key, default)
        return getattr(drift, key, default)

    source = str(_get("source", "spec"))
    source_file = str(_get("source_file", ""))
    line = _get("line", 0)
    quote = str(_get("quote", ""))

    if not quote and not source_file:
        raise ValueError("drift must carry at least quote or source_file")

    digest = hashlib.sha1(
        f"{source_file}:{line}:{quote}".encode("utf-8")
    ).hexdigest()[:8]

    slug = _slugify(quote) or _slugify(source_file) or "drift"
    return f"{prefix}/{source}-{slug}-{digest}"


def create_branch_for_drift(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    drift: Any,
    base_sha: str,
    prefix: str = "pr-guard/fix",
) -> tuple[str, Any]:
    """Generate a unique branch name from ``drift`` and create the ref.

    Returns ``(branch_name, octokit_response)``.
    """
    branch = branch_name_for_drift(drift, prefix=prefix)
    response = create_branch(
        octokit,
        owner=owner,
        repo=repo,
        branch=branch,
        base_sha=base_sha,
    )
    return branch, response
