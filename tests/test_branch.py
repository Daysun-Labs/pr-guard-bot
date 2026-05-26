"""Unit tests for branch.create_branch (Sub-AC 2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pr_guard.branch import (
    branch_name_for_drift,
    create_branch,
    create_branch_for_drift,
)
from pr_guard.drift import DriftItem


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


def _drift(quote="acceptance: API must reject bad input", line=12, source_file="PRD.md", source="prd"):
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=source_file,
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=line,
        score=0.1,
    )


def test_branch_name_for_drift_is_deterministic_and_unique():
    d1 = _drift(quote="require X", line=1)
    d2 = _drift(quote="require Y", line=2)

    n1 = branch_name_for_drift(d1)
    n2 = branch_name_for_drift(d2)

    assert n1 == branch_name_for_drift(d1)  # deterministic
    assert n1 != n2  # unique per drift
    assert n1.startswith("pr-guard/fix/prd-")
    # safe ref chars only
    assert all(c.isalnum() or c in "-/_" for c in n1)


def test_branch_name_for_drift_accepts_dict_input():
    name = branch_name_for_drift(
        {"source": "seed", "source_file": "SEED.md", "line": 7, "quote": "no hardcoded keys"}
    )
    assert name.startswith("pr-guard/fix/seed-")


def test_create_branch_for_drift_calls_mock_github_create_ref():
    octokit = _mock_octokit({"ref": "refs/heads/x", "object": {"sha": "cafef00d"}})
    drift = _drift()

    branch, response = create_branch_for_drift(
        octokit,
        owner="acme",
        repo="widgets",
        drift=drift,
        base_sha="cafef00d",
    )

    octokit.git.create_ref.assert_called_once()
    _, kwargs = octokit.git.create_ref.call_args
    assert kwargs["owner"] == "acme"
    assert kwargs["repo"] == "widgets"
    assert kwargs["sha"] == "cafef00d"
    assert kwargs["ref"] == f"refs/heads/{branch}"
    assert response == {"ref": "refs/heads/x", "object": {"sha": "cafef00d"}}


def test_create_branch_for_drift_rejects_empty_base_sha():
    octokit = _mock_octokit()
    with pytest.raises(ValueError):
        create_branch_for_drift(
            octokit, owner="o", repo="r", drift=_drift(), base_sha=""
        )
    octokit.git.create_ref.assert_not_called()
