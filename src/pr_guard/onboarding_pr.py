"""Render onboarding PR title/body for repos missing PRD/SEED.

Pure template renderer: repo metadata -> (title, body) markdown strings.
Used when the bot detects a repo without PRD.md / SEED.md and wants to
nudge the owner to run `ooo interview` to bootstrap the spec.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepoMetadata:
    """Minimal repo metadata needed to render an onboarding PR."""

    full_name: str  # e.g. "darbykim/foo"
    default_branch: str = "main"
    missing: tuple[str, ...] = ("PRD.md", "SEED.md")


def render_onboarding_pr_title(repo: RepoMetadata) -> str:
    """Render the onboarding PR title."""
    return f"[pr-guard] Bootstrap PRD/SEED for {repo.full_name} via `ooo interview`"


def render_onboarding_pr_body(repo: RepoMetadata) -> str:
    """Render the onboarding PR body as markdown.

    Pure function: deterministic output for a given input, no I/O.
    """
    missing_list = "\n".join(f"- `{name}`" for name in repo.missing) or "- (none)"
    return (
        f"# pr-guard onboarding: `{repo.full_name}`\n"
        f"\n"
        f"This repo is missing the spec files pr-guard needs to evaluate PRs "
        f"against your intended Production criteria.\n"
        f"\n"
        f"## Missing files\n"
        f"{missing_list}\n"
        f"\n"
        f"## Next step — run `ooo interview`\n"
        f"\n"
        f"From the repo root on `{repo.default_branch}`:\n"
        f"\n"
        f"```bash\n"
        f"ooo interview\n"
        f"ooo seed\n"
        f"```\n"
        f"\n"
        f"This will produce `PRD.md` and `SEED.md`. Commit them on "
        f"`{repo.default_branch}` and pr-guard will start verifying every PR "
        f"against those specs automatically.\n"
        f"\n"
        f"---\n"
        f"_This PR was generated automatically by pr-guard-bot. No code changes._\n"
    )


def render_onboarding_pr(repo: RepoMetadata) -> dict[str, str]:
    """Render both title and body. Convenience wrapper."""
    return {
        "title": render_onboarding_pr_title(repo),
        "body": render_onboarding_pr_body(repo),
    }
