"""Commit creation helpers (Sub-AC 2.5.2).

``commit_file_change`` takes a file change (path + new content + message)
and performs the commit via an octokit-style GitHub client. The commit is
created using the GitHub Contents API:

    PUT /repos/{owner}/{repo}/contents/{path}

which under-the-hood expects the client method
``client.repos.create_or_update_file_contents(...)``.

This module is deliberately small and free of network access so it can be
unit-tested by injecting a mock octokit client.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass(frozen=True)
class FileChange:
    """A single file change to commit."""

    path: str
    content: str
    message: str
    sha: Optional[str] = None  # required when updating an existing file


def _encode_content(content: Union[str, bytes]) -> str:
    """Base64-encode content for the GitHub Contents API."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return base64.b64encode(content).decode("ascii")


def commit_file_change(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    branch: str,
    change: FileChange,
    committer: Optional[dict] = None,
) -> Any:
    """Commit a single ``FileChange`` to ``branch`` via the Contents API.

    Args:
        octokit: object exposing
            ``.repos.create_or_update_file_contents(owner, repo, path, ...)``.
        owner: repository owner.
        repo: repository name.
        branch: target branch (short name).
        change: the ``FileChange`` to commit.
        committer: optional ``{"name": ..., "email": ...}`` payload.

    Returns:
        Whatever the underlying client returns (typically the commit object).

    Raises:
        ValueError: when any of branch/path/message is empty.
    """
    if not branch:
        raise ValueError("branch must be a non-empty string")
    if not change.path:
        raise ValueError("change.path must be a non-empty string")
    if not change.message:
        raise ValueError("change.message must be a non-empty string")

    payload: dict = {
        "owner": owner,
        "repo": repo,
        "path": change.path,
        "message": change.message,
        "content": _encode_content(change.content),
        "branch": branch,
    }
    if change.sha:
        payload["sha"] = change.sha
    if committer:
        payload["committer"] = committer

    return octokit.repos.create_or_update_file_contents(**payload)
