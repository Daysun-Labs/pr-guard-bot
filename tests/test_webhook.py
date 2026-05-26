import pytest

from pr_guard.webhook import (
    InvalidWebhookPayload,
    NormalizedPREvent,
    parse_pr_webhook,
)


def _valid_payload(action="opened"):
    return {
        "action": action,
        "pull_request": {
            "number": 42,
            "diff_url": "https://github.com/o/r/pull/42.diff",
            "html_url": "https://github.com/o/r/pull/42",
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "user": {"login": "darbykim"},
        },
        "repository": {"full_name": "o/r"},
    }


def test_parse_valid_payload():
    ev = parse_pr_webhook(_valid_payload())
    assert isinstance(ev, NormalizedPREvent)
    assert ev.pr_number == 42
    assert ev.repo_full_name == "o/r"
    assert ev.author == "darbykim"
    assert ev.head_branch == "feature/x"
    assert ev.base_branch == "main"
    assert ev.action == "opened"
    assert ev.diff_url.endswith(".diff")
    assert ev.to_dict()["pr_number"] == 42


def test_synchronize_action_allowed():
    ev = parse_pr_webhook(_valid_payload("synchronize"))
    assert ev.action == "synchronize"


def test_wrong_event_type():
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook(_valid_payload(), event_type="issues")


def test_none_payload():
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook(None)


def test_missing_pull_request():
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook({"action": "opened", "repository": {"full_name": "o/r"}})


def test_unsupported_action():
    p = _valid_payload("assigned")
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook(p)


def test_malformed_inner_fields():
    p = _valid_payload()
    del p["pull_request"]["head"]
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook(p)


def test_non_integer_number():
    p = _valid_payload()
    p["pull_request"]["number"] = "not-a-number"
    with pytest.raises(InvalidWebhookPayload):
        parse_pr_webhook(p)
