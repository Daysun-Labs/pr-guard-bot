"""Publish PR comments via the GitHub REST API.

Sub-AC 2: Octokit(httpx)-기반 클라이언트로 PR 코멘트를 게시하는 publish 함수.

GitHub REST endpoint:
    POST /repos/{owner}/{repo}/issues/{issue_number}/comments

PR 코멘트는 issues comments 엔드포인트를 사용한다 (PR도 issue로 취급).
"""

from __future__ import annotations

from typing import Any

import httpx


class PublishError(RuntimeError):
    """Raised when the GitHub API rejects a comment publish request."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"GitHub API {status_code}: {message}")
        self.status_code = status_code
        self.message = message


def publish_pr_comment(
    client: httpx.Client,
    *,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    marker: str | None = None,
) -> dict[str, Any]:
    """Post a comment to a pull request.

    Args:
        client: Authenticated httpx.Client from github_client.create_github_client.
        owner: Repository owner (user or org).
        repo: Repository name.
        pr_number: Pull request number.
        body: Markdown body of the comment.
        marker: Optional HTML marker. When present, pr-guard updates the first
            existing PR comment containing the marker instead of posting a new
            comment on every run.

    Returns:
        Parsed JSON response from GitHub (the created comment).

    Raises:
        ValueError: when owner/repo/body are empty or pr_number is non-positive.
        PublishError: when GitHub returns a non-2xx status.
    """
    if not owner:
        raise ValueError("owner is required")
    if not repo:
        raise ValueError("repo is required")
    if pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")
    if not body or not body.strip():
        raise ValueError("body must be a non-empty string")

    path = f"/repos/{owner}/{repo}/issues/{pr_number}/comments"
    publish_body = _with_marker(body, marker)
    existing_id = _find_existing_marker_comment(client, path=path, marker=marker)

    if existing_id is not None:
        response = client.patch(
            f"/repos/{owner}/{repo}/issues/comments/{existing_id}",
            json={"body": publish_body},
        )
    else:
        response = client.post(path, json={"body": publish_body})

    if response.status_code >= 400:
        try:
            payload = response.json()
            msg = payload.get("message", response.text)
        except Exception:
            msg = response.text
        raise PublishError(response.status_code, msg)

    return response.json()


def _with_marker(body: str, marker: str | None) -> str:
    if not marker:
        return body
    return body if marker in body else f"{marker}\n{body}"


def _find_existing_marker_comment(
    client: httpx.Client,
    *,
    path: str,
    marker: str | None,
) -> int | None:
    if not marker:
        return None

    response = client.get(path, params={"per_page": 100})
    if response.status_code >= 400:
        return None
    try:
        comments = response.json()
    except Exception:
        return None
    if not isinstance(comments, list):
        return None
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if marker in str(comment.get("body", "")):
            comment_id = comment.get("id")
            return int(comment_id) if comment_id is not None else None
    return None
