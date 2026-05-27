from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pr-guard.yml"


def test_workflow_uses_artifact_only_mode_for_public_fork_prs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "IS_FORK_PR" in workflow
    assert "head.repo.full_name != github.repository" in workflow
    assert "extra_args+=(--no-publish)" in workflow


def test_workflow_defaults_to_least_privilege_and_no_fix_pr_branches() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read\n  pull-requests: write\n  issues: write" in workflow
    assert "PR_GUARD_MAX_FIX_PRS: ${{ vars.PR_GUARD_MAX_FIX_PRS || '0' }}" in workflow
    assert "--publish-best-effort" in workflow
