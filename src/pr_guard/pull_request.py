"""Pull request opener (Sub-AC 3).

`open_pull_request` (a.k.a. openPullRequest) opens a PR on a repository
via an octokit-style client exposing `client.pulls.create(...)`. Returns
the created PR's number.
"""

from __future__ import annotations

from typing import Any, Optional


def open_pull_request(
    octokit: Any,
    *,
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: Optional[str] = None,
    draft: bool = False,
) -> int:
    """Open a PR from `head` into `base` and return the new PR number.

    Args:
        octokit: object exposing `.pulls.create(...)`.
        owner: repository owner.
        repo: repository name.
        head: source branch (short name).
        base: target branch (short name).
        title: PR title.
        body: optional PR body.
        draft: whether to open as a draft PR.

    Returns:
        The created PR's number (int).

    Raises:
        ValueError: when required string args are empty.
    """
    if not owner:
        raise ValueError("owner must be a non-empty string")
    if not repo:
        raise ValueError("repo must be a non-empty string")
    if not head:
        raise ValueError("head must be a non-empty string")
    if not base:
        raise ValueError("base must be a non-empty string")
    if not title:
        raise ValueError("title must be a non-empty string")

    kwargs = {
        "owner": owner,
        "repo": repo,
        "head": head,
        "base": base,
        "title": title,
        "draft": draft,
    }
    if body is not None:
        kwargs["body"] = body

    response = octokit.pulls.create(**kwargs)

    # Support both dict-style and attribute-style responses.
    if isinstance(response, dict):
        number = response.get("number")
    else:
        number = getattr(response, "number", None)

    if number is None:
        raise ValueError("pulls.create response missing 'number'")
    return int(number)
