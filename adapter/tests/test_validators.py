from __future__ import annotations

from pr_guard_adapter.models import BlockingDriftRequest, ProposalRequest
from pr_guard_adapter.validators import (
    parse_model_proposal,
    validate_blocking_decision,
    validate_proposal,
)


def test_parse_model_proposal_accepts_json_inside_markdown_fence() -> None:
    result = parse_model_proposal(
        '```json\n{"action":"skip","reason":"not enough context"}\n```'
    )

    assert result == {"action": "skip", "reason": "not enough context"}


def test_seed_fix_rejects_non_seed_drift_source() -> None:
    request = ProposalRequest.model_validate(
        {
            "task": "seed_fix",
            "drift": {
                "source": "prd",
                "source_file": "PRD.md",
                "line": 1,
                "quote": "Add OAuth login",
                "severity": "high",
                "score": 0.5,
            },
            "seed_md_text": "# SEED\n\nOld content\n",
            "seed_md_path": "SEED.md",
            "proposal_shape": ["action", "new_content", "message", "rationale"],
        }
    )

    result = validate_proposal(
        {
            "action": "update",
            "new_content": "# SEED\n\nAdd OAuth login\n",
            "message": "docs(seed): add OAuth login",
            "rationale": "Aligns the seed with the stated drift.",
        },
        request=request,
    )

    assert result["action"] == "skip"
    assert "seed_fix requires seed drift" in result["reason"]


def test_code_fix_rejects_direct_source_patch_paths() -> None:
    request = ProposalRequest.model_validate(
        {
            "task": "code_fix",
            "drift": {
                "source": "prd",
                "source_file": "PRD.md",
                "line": 1,
                "quote": "Add OAuth login",
                "severity": "high",
                "score": 0.5,
            },
            "repo_context": "src/app.py\n",
            "output_path": "src/app.py",
            "proposal_shape": ["action", "new_content", "message", "rationale"],
        }
    )

    result = validate_proposal(
        {
            "action": "update",
            "new_content": "# Proposal\n\nChange source code directly.",
            "message": "fix: change source",
            "rationale": "Would patch source code.",
        },
        request=request,
    )

    assert result["action"] == "skip"
    assert "docs/pr-guard-proposals" in result["reason"]


def test_update_flattens_multiline_commit_message() -> None:
    request = ProposalRequest.model_validate(
        {
            "task": "code_fix",
            "drift": {
                "source": "prd",
                "source_file": "PRD.md",
                "line": 1,
                "quote": "Add OAuth login",
                "severity": "high",
                "score": 0.5,
            },
            "repo_context": "src/app.py\n",
            "output_path": "docs/pr-guard-proposals/oauth-login.md",
            "proposal_shape": ["action", "new_content", "message", "rationale"],
        }
    )

    result = validate_proposal(
        {
            "action": "update",
            "new_content": "# Proposal\n\n## Missing requirement\nAdd OAuth login",
            "message": "docs: add OAuth\n\nBody not allowed",
            "rationale": "Creates a reviewable proposal.",
        },
        request=request,
    )

    assert result["action"] == "update"
    assert result["message"] == "docs: add OAuth Body not allowed"


def test_blocking_decision_drops_invalid_indexes_and_nonblocking_entries() -> None:
    request = BlockingDriftRequest.model_validate(
        {
            "task": "blocking_drift_classification",
            "advisory_drifts": [
                {
                    "source": "prd",
                    "source_file": "PRD.md",
                    "line": 1,
                    "quote": "Add OAuth login",
                    "severity": "high",
                    "score": 0.33,
                }
            ],
            "diff_summary": "FILE src/app.py",
        }
    )

    result = validate_blocking_decision(
        {
            "blocking": [
                {"index": 0, "reason": "Scoped auth code still omits OAuth."},
                {"index": 0, "reason": "duplicate"},
                {"index": 99, "reason": "out of range"},
                {"index": 0, "decision": "advisory", "reason": "not blocking"},
            ]
        },
        request=request,
    )

    assert result == {
        "blocking": [
            {
                "index": 0,
                "reason": "Scoped auth code still omits OAuth.",
            }
        ]
    }
