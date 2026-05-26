"""Unit tests for patcher — Claude SDK is stubbed via Protocol."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pr_guard.drift import DriftItem
from pr_guard.patcher import (
    PatchProposal,
    generate_code_fix_proposal,
    generate_seed_fix,
)


# ──────────────────────────────────────────────────────────────────────────
# Fake Claude client (anthropic.messages shape)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _FakeBlock:
    text: str


@dataclass
class _FakeResp:
    content: list[_FakeBlock]


class FakeClaude:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _FakeResp:
        self.last_kwargs = kwargs
        return _FakeResp(content=[_FakeBlock(text=self.response_text)])


def _drift(*, source: str = "seed", quote: str = "PR comment within 5 min") -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=f"{source.upper()}.md",
        section="Acceptance",
        kind="acceptance",
        quote=quote,
        line=42,
        score=0.5,
    )


# ──────────────────────────────────────────────────────────────────────────
# generate_seed_fix
# ──────────────────────────────────────────────────────────────────────────


def test_seed_fix_returns_proposal_on_update_action() -> None:
    claude = FakeClaude(
        json.dumps(
            {
                "action": "update",
                "new_content": "# SEED\nupdated line\n",
                "message": "docs(seed): align with PR reality",
                "rationale": "PR moved to 10 min SLA; spec needs to match.",
            }
        )
    )
    proposal = generate_seed_fix(
        _drift(source="seed"),
        seed_md_text="# SEED\nold line\n",
        client=claude,
    )
    assert isinstance(proposal, PatchProposal)
    assert proposal.change.path == "SEED.md"
    assert proposal.change.content.startswith("# SEED")
    assert "5 min" not in proposal.change.content
    assert proposal.rationale.startswith("PR moved")


def test_seed_fix_returns_none_on_skip() -> None:
    claude = FakeClaude(
        json.dumps({"action": "skip", "reason": "looks like a regression"})
    )
    assert generate_seed_fix(_drift(), seed_md_text="x", client=claude) is None


def test_seed_fix_returns_none_on_malformed_json() -> None:
    claude = FakeClaude("not json at all { definitely not }")
    assert generate_seed_fix(_drift(), seed_md_text="x", client=claude) is None


def test_seed_fix_handles_fenced_response() -> None:
    payload = json.dumps(
        {"action": "update", "new_content": "x", "message": "m", "rationale": "r"}
    )
    claude = FakeClaude(f"```json\n{payload}\n```")
    proposal = generate_seed_fix(_drift(), seed_md_text="y", client=claude)
    assert proposal is not None
    assert proposal.change.content == "x"


def test_seed_fix_returns_none_when_new_content_empty() -> None:
    claude = FakeClaude(
        json.dumps({"action": "update", "new_content": "", "message": "m", "rationale": "r"})
    )
    assert generate_seed_fix(_drift(), seed_md_text="x", client=claude) is None


def test_seed_fix_passes_system_with_prompt_cache() -> None:
    claude = FakeClaude(
        json.dumps(
            {"action": "update", "new_content": "x", "message": "m", "rationale": "r"}
        )
    )
    generate_seed_fix(_drift(), seed_md_text="x", client=claude)
    sys_blocks = claude.last_kwargs["system"]
    assert isinstance(sys_blocks, list) and len(sys_blocks) == 1
    assert sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "JSON" in sys_blocks[0]["text"]


# ──────────────────────────────────────────────────────────────────────────
# generate_code_fix_proposal
# ──────────────────────────────────────────────────────────────────────────


def test_code_fix_returns_proposal_under_docs_dir() -> None:
    claude = FakeClaude(
        json.dumps(
            {
                "action": "update",
                "new_content": "# Proposal\n\n...analysis...\n",
                "message": "docs(proposal): outline plan for X",
                "rationale": "Suggests a 3-step approach.",
            }
        )
    )
    proposal = generate_code_fix_proposal(
        _drift(source="prd", quote="implement payment integration"),
        repo_context="(repo file tree summary)",
        client=claude,
    )
    assert proposal is not None
    assert proposal.change.path.startswith("docs/pr-guard-proposals/")
    assert proposal.change.path.endswith(".md")
    assert proposal.change.content.startswith("# Proposal")


def test_code_fix_returns_none_on_skip() -> None:
    claude = FakeClaude(json.dumps({"action": "skip", "reason": "too vague"}))
    assert (
        generate_code_fix_proposal(_drift(source="prd"), repo_context="", client=claude)
        is None
    )


def test_code_fix_slug_is_stable_for_same_drift() -> None:
    claude_a = FakeClaude(
        json.dumps(
            {"action": "update", "new_content": "x", "message": "m", "rationale": "r"}
        )
    )
    claude_b = FakeClaude(
        json.dumps(
            {"action": "update", "new_content": "x", "message": "m", "rationale": "r"}
        )
    )
    drift = _drift(source="prd", quote="add observability dashboard")
    p1 = generate_code_fix_proposal(drift, repo_context="", client=claude_a)
    p2 = generate_code_fix_proposal(drift, repo_context="", client=claude_b)
    assert p1 is not None and p2 is not None
    assert p1.change.path == p2.change.path
