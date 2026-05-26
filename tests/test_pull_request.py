"""Unit tests for pull_request.open_pull_request (Sub-AC 3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pr_guard.pull_request import open_pull_request


def _mock_octokit(return_value=None):
    octokit = MagicMock()
    octokit.pulls.create = MagicMock(
        return_value=return_value if return_value is not None else {"number": 42}
    )
    return octokit


def test_open_pull_request_calls_pulls_create_with_expected_args():
    octokit = _mock_octokit({"number": 101, "html_url": "https://x/pr/101"})

    number = open_pull_request(
        octokit,
        owner="acme",
        repo="widgets",
        head="fix/x",
        base="main",
        title="Fix X",
        body="see PRD",
    )

    octokit.pulls.create.assert_called_once_with(
        owner="acme",
        repo="widgets",
        head="fix/x",
        base="main",
        title="Fix X",
        body="see PRD",
        draft=False,
    )
    assert number == 101


def test_open_pull_request_omits_body_when_none():
    octokit = _mock_octokit({"number": 7})
    open_pull_request(
        octokit, owner="o", repo="r", head="h", base="main", title="t"
    )
    _, kwargs = octokit.pulls.create.call_args
    assert "body" not in kwargs
    assert kwargs["draft"] is False


def test_open_pull_request_returns_pr_number_as_int():
    octokit = _mock_octokit({"number": "55"})
    n = open_pull_request(
        octokit, owner="o", repo="r", head="h", base="main", title="t"
    )
    assert n == 55
    assert isinstance(n, int)


def test_open_pull_request_supports_attribute_style_response():
    response = MagicMock()
    response.number = 9
    # Avoid dict-instance match by not making it a dict.
    octokit = MagicMock()
    octokit.pulls.create = MagicMock(return_value=response)

    n = open_pull_request(
        octokit, owner="o", repo="r", head="h", base="main", title="t"
    )
    assert n == 9


def test_open_pull_request_passes_draft_flag():
    octokit = _mock_octokit({"number": 3})
    open_pull_request(
        octokit,
        owner="o",
        repo="r",
        head="h",
        base="main",
        title="t",
        draft=True,
    )
    _, kwargs = octokit.pulls.create.call_args
    assert kwargs["draft"] is True


@pytest.mark.parametrize(
    "field",
    ["owner", "repo", "head", "base", "title"],
)
def test_open_pull_request_rejects_empty_required_fields(field):
    octokit = _mock_octokit()
    args = dict(owner="o", repo="r", head="h", base="main", title="t")
    args[field] = ""
    with pytest.raises(ValueError, match=field):
        open_pull_request(octokit, **args)
    octokit.pulls.create.assert_not_called()


def test_open_pull_request_raises_when_response_missing_number():
    octokit = _mock_octokit({"html_url": "x"})
    with pytest.raises(ValueError, match="number"):
        open_pull_request(
            octokit, owner="o", repo="r", head="h", base="main", title="t"
        )
