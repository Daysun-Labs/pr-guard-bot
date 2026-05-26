"""pr-guard entrypoint — invoked from GitHub Actions on pull_request events.

This is a SKELETON. The actual L1 oracle implementation (ooo evaluate
integration), drift classification, and fix-PR generation logic are
intentionally left as TODOs — these will be implemented through the
bot's own dogfooding cycle (interview → seed → run → evolve).

Architecture: see SEED.md "아키텍처" section.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# ──────────────────────────────────────────────────────────────────────────
# Data structures matching SEED.yaml ontology_schema (PRGuardSession)
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class PRMetadata:
    repo: str
    pr_number: int
    base_ref: str
    head_ref: str
    diff_url: str | None = None


@dataclass
class DriftFinding:
    type: str                          # e.g. "missing_acceptance_criterion"
    severity: Literal["low", "medium", "high"]
    source: Literal["prd", "seed"]
    quote: str                         # PRD/SEED에서 위반된 문구
    location: str | None = None        # PR 내 파일·라인 또는 PRD/SEED 위치


@dataclass
class FixPRProposal:
    kind: Literal["code", "seed"]
    rationale: str
    patch: str | None = None           # unified diff (None이면 LLM이 생성 예정)


@dataclass
class PRGuardSession:
    pr_metadata: PRMetadata
    prd_intent: dict = field(default_factory=dict)
    seed_spec: dict = field(default_factory=dict)
    diff_analysis: dict = field(default_factory=dict)
    drift_findings: list[DriftFinding] = field(default_factory=list)
    fix_pr_proposals: list[FixPRProposal] = field(default_factory=list)
    notification_payload: dict = field(default_factory=dict)
    oracle_level_used: Literal["L1", "L2", "L3"] = "L1"
    repo_health_state: Literal["no_prd_seed", "drift_detected", "aligned"] = "aligned"


# ──────────────────────────────────────────────────────────────────────────
# Pipeline steps (see SEED.md "아키텍처" diagram)
# ──────────────────────────────────────────────────────────────────────────


def load_intent_docs(repo_root: Path) -> tuple[str | None, str | None]:
    """Read PRD.md + SEED.md from the PR's checked-out tree.

    Returns (prd_text, seed_text). Either may be None if the file is absent.
    """
    prd_path = repo_root / "PRD.md"
    seed_path = repo_root / "SEED.md"
    prd = prd_path.read_text(encoding="utf-8") if prd_path.exists() else None
    seed = seed_path.read_text(encoding="utf-8") if seed_path.exists() else None
    return prd, seed


def compute_pr_diff(base_ref: str, head_ref: str) -> str:
    """Compute unified diff between base and head."""
    result = subprocess.run(
        ["git", "diff", f"origin/{base_ref}...{head_ref}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def evaluate_drift(
    *,
    prd: str,
    seed: str,
    diff: str,
    oracle_level: str = "L1",
) -> list[DriftFinding]:
    """L1 oracle: 정적 의미 정합성 분석.

    TODO(dogfood-iteration-1):
        - ooo evaluate MCP 호출 또는 claude-agent-sdk 직접 호출로 구현
        - 입력: PRD/SEED 텍스트 + PR diff
        - 출력: drift_findings 리스트 (PRD vs SEED 소스 명시)

    L2/L3는 향후 도입.
    """
    raise NotImplementedError("L1 oracle: ooo evaluate 통합 — dogfood로 구현 예정")


def classify_and_propose_fixes(
    findings: list[DriftFinding],
) -> list[FixPRProposal]:
    """drift 분류 규칙 (SEED.md "Fix PR 분류 규칙" 참조).

    PRD 위반 → code-fix, SEED 위반 → seed-fix.
    """
    proposals: list[FixPRProposal] = []
    for f in findings:
        if f.source == "prd":
            proposals.append(
                FixPRProposal(
                    kind="code",
                    rationale=f"PR이 PRD 의도와 어김: {f.quote}",
                )
            )
        elif f.source == "seed":
            proposals.append(
                FixPRProposal(
                    kind="seed",
                    rationale=f"PR이 SEED 명세와 어김: {f.quote}",
                )
            )
    return proposals


def post_pr_comment(
    *, repo: str, pr_number: int, body: str, gh_token: str
) -> None:
    """GitHub API로 PR 코멘트 작성."""
    raise NotImplementedError("GitHub API 코멘트 작성 — PyGithub로 구현")


def create_fix_pr(
    *,
    repo: str,
    pr_number: int,
    proposal: FixPRProposal,
    gh_token: str,
) -> str:
    """수정 PR 생성. 브랜치 네이밍 규칙은 SEED.md 참조.

    Returns: 생성된 수정 PR의 URL
    """
    branch_name = f"pr-guard/{proposal.kind}-fix/{pr_number}"
    raise NotImplementedError(
        f"수정 PR 생성: branch={branch_name}, kind={proposal.kind}"
    )


def notify_slack(*, payload: dict, webhook_url: str) -> None:
    """Slack incoming webhook 호출. 실패해도 main flow 중단 금지."""
    import httpx

    try:
        httpx.post(webhook_url, json=payload, timeout=10).raise_for_status()
    except Exception as e:
        print(f"⚠️ Slack 알림 실패 (계속 진행): {e}", file=sys.stderr)


def render_onboarding_comment() -> str:
    """PRD/SEED 없는 리포에 보낼 안내 코멘트."""
    return (
        "👋 **pr-guard**: 이 리포에 `PRD.md` 또는 `SEED.md`가 없어 의도 기반 "
        "검증을 수행할 수 없어요.\n\n"
        "다음을 실행해 두 문서를 부트스트랩하세요:\n\n"
        "```bash\n"
        "ooo interview \"이 제품이 무엇이고 왜 만드는지 정의\"\n"
        "ooo seed   # → PRD.md + SEED.md 생성\n"
        "```\n\n"
        "이 두 파일이 main 브랜치에 들어오면 다음 PR부터 자동 검증됩니다."
    )


# ──────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pr-guard")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Checked-out PR working tree (default: cwd)",
    )
    args = parser.parse_args(argv)

    gh_token = os.environ.get("GITHUB_TOKEN")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not gh_token:
        print("ERROR: GITHUB_TOKEN env var 필요", file=sys.stderr)
        return 1

    session = PRGuardSession(
        pr_metadata=PRMetadata(
            repo=args.repo,
            pr_number=args.pr_number,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
    )

    # 1) Load PRD + SEED
    prd, seed = load_intent_docs(args.repo_root)
    if prd is None or seed is None:
        session.repo_health_state = "no_prd_seed"
        post_pr_comment(
            repo=args.repo,
            pr_number=args.pr_number,
            body=render_onboarding_comment(),
            gh_token=gh_token,
        )
        if slack_webhook:
            notify_slack(
                payload={
                    "text": (
                        f"📭 `{args.repo}#{args.pr_number}` — PRD/SEED 없음, "
                        f"안내 코멘트 전송."
                    )
                },
                webhook_url=slack_webhook,
            )
        return 0

    session.prd_intent = {"raw": prd}
    session.seed_spec = {"raw": seed}

    # 2) Compute diff
    diff = compute_pr_diff(args.base_ref, args.head_ref)
    session.diff_analysis = {"unified_diff": diff}

    # 3) Evaluate drift (L1)
    findings = evaluate_drift(prd=prd, seed=seed, diff=diff)
    session.drift_findings = findings

    # 4) Classify & propose fixes
    proposals = classify_and_propose_fixes(findings)
    session.fix_pr_proposals = proposals
    session.repo_health_state = "drift_detected" if findings else "aligned"

    # 5) Notify
    comment_body = json.dumps(
        {
            "drift_count": len(findings),
            "fixes_proposed": [p.kind for p in proposals],
        },
        ensure_ascii=False,
        indent=2,
    )
    post_pr_comment(
        repo=args.repo,
        pr_number=args.pr_number,
        body=f"## pr-guard report\n\n```json\n{comment_body}\n```",
        gh_token=gh_token,
    )
    for proposal in proposals:
        create_fix_pr(
            repo=args.repo,
            pr_number=args.pr_number,
            proposal=proposal,
            gh_token=gh_token,
        )
    if slack_webhook:
        notify_slack(
            payload={
                "text": (
                    f"🛡 `{args.repo}#{args.pr_number}` — "
                    f"drift {len(findings)}건, fix-PR {len(proposals)}건 생성"
                )
            },
            webhook_url=slack_webhook,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
