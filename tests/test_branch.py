"""Unit tests for branch.create_branch (Sub-AC 2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pr_guard.branch import create_branch


def _mock_octokit(return_value=None):
    octokit = MagicMock()
    octokit.git.create_ref = MagicMock(return_value=return_value or {"ref": "ok"})
    return octokit


def test_create_branch_calls_create_ref_with_canonical_args():
    octokit = _mock_octokit({"ref": "refs/heads/fix/x", "object": {"sha": "deadbeef"}})

    result = create_branch(
        octokit,
        owner="acme",
        repo="widgets",
        branch="fix/x",
        base_sha="deadbeef",
    )

    octokit.git.create_ref.assert_called_once_with(
        owner="acme",
        repo="widgets",
        ref="refs/heads/fix/x",
        sha="deadbeef",
    )
    assert result == {"ref": "refs/heads/fix/x", "object": {"sha": "deadbeef"}}


def test_create_branch_prefixes_refs_heads():
    octokit = _mock_octokit()
    create_branch(
        octokit, owner="o", repo="r", branch="feature-1", base_sha="abc123"
    )
    _, kwargs = octokit.git.create_ref.call_args
    assert kwargs["ref"] == "refs/heads/feature-1"
    assert kwargs["sha"] == "abc123"


def test_create_branch_rejects_empty_branch():
    octokit = _mock_octokit()
    with pytest.raises(ValueError, match="branch"):
        create_branch(octokit, owner="o", repo="r", branch="", base_sha="abc")
    octokit.git.create_ref.assert_not_called()


def test_create_branch_rejects_empty_sha():
    octokit = _mock_octokit()
    with pytest.raises(ValueError, match="base_sha"):
        create_branch(octokit, owner="o", repo="r", branch="b", base_sha="")
    octokit.git.create_ref.assert_not_called()


def test_create_branch_rejects_full_ref_name():
    octokit = _mock_octokit()
    with pytest.raises(ValueError, match="short name"):
        create_branch(
            octokit,
            owner="o",
            repo="r",
            branch="refs/heads/already-prefixed",
            base_sha="abc",
        )
    octokit.git.create_ref.assert_not_called()
