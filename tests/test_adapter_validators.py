from __future__ import annotations

from pr_guard_adapter.models import ProposalRequest
from pr_guard_adapter.validators import validate_proposal


def _code_fix_request() -> ProposalRequest:
    return ProposalRequest.model_validate(
        {
            "task": "code_fix",
            "metadata": {"repo": "Daysun-Labs/astate-brain", "pr_number": 23},
            "drift": {
                "source": "prd",
                "quote": "Web minimal surface는 landing, sign-in, Privacy Center skeleton, chat export upload, admin tenant list를 제공해야 한다.",
                "source_file": "PRD.md",
                "line": 11,
                "severity": "medium",
                "score": 0.3333,
            },
            "proposal_shape": ["action", "new_content", "message", "rationale"],
            "repo_context": "smoke context",
            "output_path": "docs/pr-guard-proposals/smoke-web-minimal-surface.md",
        }
    )


def test_validate_proposal_truncates_overlong_one_line_message() -> None:
    result = validate_proposal(
        {
            "action": "update",
            "new_content": "# Proposal\n\nReview the smoke PR and do not merge it as-is.",
            "message": "Create a very detailed proposal title that is useful to a human reviewer but exceeds the GitHub commit subject limit enforced by the adapter",
            "rationale": "The proposal body is safe; only the one-line title needs trimming.",
        },
        request=_code_fix_request(),
    )

    assert result["action"] == "update"
    assert len(result["message"]) <= 120
    assert result["message"].endswith("…")


def test_validate_proposal_flattens_multiline_message() -> None:
    result = validate_proposal(
        {
            "action": "update",
            "new_content": "# Proposal\n\nReview the smoke PR and do not merge it as-is.",
            "message": "Draft proposal\nfor PR Guard smoke",
            "rationale": "The adapter should normalize harmless formatting drift.",
        },
        request=_code_fix_request(),
    )

    assert result["action"] == "update"
    assert result["message"] == "Draft proposal for PR Guard smoke"
