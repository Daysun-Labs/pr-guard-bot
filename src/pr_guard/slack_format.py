"""Pure formatter: NormalizedPREvent -> Slack incoming-webhook payload."""
from __future__ import annotations

from typing import Any

from .webhook import NormalizedPREvent


_ACTION_VERB = {
    "opened": "opened",
    "reopened": "reopened",
    "synchronize": "updated",
    "edited": "edited",
    "ready_for_review": "marked ready for review",
    "closed": "closed",
}


def format_pr_event_for_slack(event: NormalizedPREvent) -> dict[str, Any]:
    """Format a normalized PR event into a Slack incoming-webhook JSON payload.

    Pure function: no I/O, deterministic output for a given input.
    """
    verb = _ACTION_VERB.get(event.action, event.action)
    title = (
        f"[{event.repo_full_name}] PR #{event.pr_number} {verb} by {event.author}"
    )
    context_text = (
        f"{event.head_branch} → {event.base_branch} · "
        f"<{event.html_url}|view PR> · <{event.diff_url}|diff>"
    )
    return {
        "text": title,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*"},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            },
        ],
    }
