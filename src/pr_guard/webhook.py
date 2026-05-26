"""GitHub PR webhook receiver: parse payload to a normalized event."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


class InvalidWebhookPayload(ValueError):
    """Raised when a GitHub PR webhook payload is missing required fields."""


@dataclass(frozen=True)
class NormalizedPREvent:
    action: str
    pr_number: int
    repo_full_name: str
    author: str
    head_branch: str
    base_branch: str
    diff_url: str
    html_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ALLOWED_ACTIONS = {
    "opened", "reopened", "synchronize", "edited", "ready_for_review", "closed"
}


def parse_pr_webhook(
    payload: Mapping[str, Any] | None,
    event_type: str = "pull_request",
) -> NormalizedPREvent:
    """Parse a GitHub `pull_request` webhook payload into a normalized event.

    Raises InvalidWebhookPayload if the payload is missing required fields or
    is not a supported pull_request event.
    """
    if event_type != "pull_request":
        raise InvalidWebhookPayload(f"unsupported event type: {event_type!r}")
    if not isinstance(payload, Mapping):
        raise InvalidWebhookPayload("payload must be a mapping")

    action = payload.get("action")
    pr = payload.get("pull_request")
    repo = payload.get("repository")
    if not isinstance(action, str) or not isinstance(pr, Mapping) or not isinstance(repo, Mapping):
        raise InvalidWebhookPayload("missing action/pull_request/repository")
    if action not in _ALLOWED_ACTIONS:
        raise InvalidWebhookPayload(f"unsupported action: {action!r}")

    try:
        number = int(pr["number"])
        head = pr["head"]
        base = pr["base"]
        user = pr["user"]
        diff_url = str(pr["diff_url"])
        html_url = str(pr["html_url"])
        repo_full = str(repo["full_name"])
        head_ref = str(head["ref"])
        base_ref = str(base["ref"])
        author = str(user["login"])
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidWebhookPayload(f"malformed pull_request payload: {e}") from e

    return NormalizedPREvent(
        action=action,
        pr_number=number,
        repo_full_name=repo_full,
        author=author,
        head_branch=head_ref,
        base_branch=base_ref,
        diff_url=diff_url,
        html_url=html_url,
    )
