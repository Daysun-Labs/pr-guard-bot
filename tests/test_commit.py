"""Unit tests for commit.commit_file_change (Sub-AC 2.5.2)."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest

from pr_guard.commit import FileChange, commit_file_change


def _mock_octokit(return_value=None):
    octokit = MagicMock()
    octokit.repos.create_or_update_file_contents = MagicMock(
        return_value=return_value or {"commit": {"sha": "abc123"}}
    )
    return octokit


def test_commit_file_change_calls_contents_api_with_base64_content():
    octokit = _mock_octokit()
    change = FileChange(
        path="docs/fix.md",
        content="hello world",
        message="fix: tweak docs",
    )

    result = commit_file_change(
        octokit,
        owner="acme",
        repo="widgets",
        branch="pr-guard/fix/x",
        change=change,
    )

    octokit.repos.create_or_update_file_contents.assert_called_once()
    _, kwargs = octokit.repos.create_or_update_file_contents.call_args
    assert kwargs["owner"] == "acme"
    assert kwargs["repo"] == "widgets"
    assert kwargs["path"] == "docs/fix.md"
    assert kwargs["branch"] == "pr-guard/fix/x"
    assert kwargs["message"] == "fix: tweak docs"
    assert base64.b64decode(kwargs["content"]).decode() == "hello world"
    assert "sha" not in kwargs
    assert result == {"commit": {"sha": "abc123"}}


def test_commit_file_change_includes_sha_when_updating_existing_file():
    octokit = _mock_octokit()
    change = FileChange(
        path="PRD.md",
        content="updated",
        message="chore: update PRD",
        sha="deadbeef",
    )

    commit_file_change(
        octokit, owner="o", repo="r", branch="b", change=change
    )
    _, kwargs = octokit.repos.create_or_update_file_contents.call_args
    assert kwargs["sha"] == "deadbeef"


def test_commit_file_change_passes_committer_when_provided():
    octokit = _mock_octokit()
    change = FileChange(path="a.txt", content="x", message="m")
    committer = {"name": "pr-guard-bot", "email": "bot@example.com"}

    commit_file_change(
        octokit,
        owner="o",
        repo="r",
        branch="b",
        change=change,
        committer=committer,
    )
    _, kwargs = octokit.repos.create_or_update_file_contents.call_args
    assert kwargs["committer"] == committer


def test_commit_file_change_encodes_bytes_content():
    octokit = _mock_octokit()
    change = FileChange(path="bin.dat", content=b"\x00\x01\x02", message="m")  # type: ignore[arg-type]

    commit_file_change(octokit, owner="o", repo="r", branch="b", change=change)
    _, kwargs = octokit.repos.create_or_update_file_contents.call_args
    assert base64.b64decode(kwargs["content"]) == b"\x00\x01\x02"


def test_commit_file_change_rejects_empty_branch():
    octokit = _mock_octokit()
    change = FileChange(path="a.txt", content="x", message="m")
    with pytest.raises(ValueError, match="branch"):
        commit_file_change(octokit, owner="o", repo="r", branch="", change=change)
    octokit.repos.create_or_update_file_contents.assert_not_called()


def test_commit_file_change_rejects_empty_path():
    octokit = _mock_octokit()
    change = FileChange(path="", content="x", message="m")
    with pytest.raises(ValueError, match="path"):
        commit_file_change(octokit, owner="o", repo="r", branch="b", change=change)
    octokit.repos.create_or_update_file_contents.assert_not_called()


def test_commit_file_change_rejects_empty_message():
    octokit = _mock_octokit()
    change = FileChange(path="a.txt", content="x", message="")
    with pytest.raises(ValueError, match="message"):
        commit_file_change(octokit, owner="o", repo="r", branch="b", change=change)
    octokit.repos.create_or_update_file_contents.assert_not_called()
