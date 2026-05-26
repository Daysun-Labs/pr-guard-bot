"""pr-guard entrypoint — invoked from GitHub Actions on pull_request events.

파이프라인:
  1. PRD/SEED 존재 여부 검사 → 없으면 onboarding PR 생성 후 종료
  2. PRD + SEED 파싱 → Requirement 추출
  3. PR diff 추출 → NormalizedDiff
  4. drift 감지 + 코멘트 렌더 + PR 코멘트 게시
  5. Slack 알림 (옵션)

Fix-PR(code-fix/seed-fix) 자동 생성은 LLM 패치 생성이 필요하므로
이번 라운드에서는 코멘트에 분류 결과만 첨부 — dogfood 라운드 2에서 추가.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from .comment_format import format_drift_comment
from .detector import detect_spec_files
from .diff_extractor import parse_unified_diff
from .drift import DriftItem, detect_drift, filter_actionable_drift
from .fix_pr import create_fix_pr
from .github_client import create_github_client
from .onboarding_orchestrator import run_onboarding
from .patcher import generate_code_fix_proposal, generate_seed_fix
from .publish import publish_pr_comment
from .slack_notify import send_slack_webhook
from .spec_parser import parse_repo


MAX_FIX_PRS_DEFAULT = 3


# ──────────────────────────────────────────────────────────────────────────
# Octokit-style adapter over httpx.Client
# ──────────────────────────────────────────────────────────────────────────


class _Pulls:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def create(
        self,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str | None = None,
        draft: bool = False,
    ) -> dict:
        payload: dict = {"head": head, "base": base, "title": title, "draft": draft}
        if body is not None:
            payload["body"] = body
        r = self._http.post(f"/repos/{owner}/{repo}/pulls", json=payload)
        r.raise_for_status()
        return r.json()

    def list(self, *, owner: str, repo: str, state: str = "open") -> list:
        r = self._http.get(f"/repos/{owner}/{repo}/pulls", params={"state": state})
        r.raise_for_status()
        return r.json()


class _Git:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def create_ref(self, *, owner: str, repo: str, ref: str, sha: str) -> dict:
        r = self._http.post(
            f"/repos/{owner}/{repo}/git/refs", json={"ref": ref, "sha": sha}
        )
        r.raise_for_status()
        return r.json()


class _Repos:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def create_or_update_file_contents(
        self, *, owner: str, repo: str, path: str, **payload: Any
    ) -> dict:
        body = {k: v for k, v in payload.items() if v is not None}
        r = self._http.put(f"/repos/{owner}/{repo}/contents/{path}", json=body)
        r.raise_for_status()
        return r.json()


class OctokitAdapter:
    """Minimal octokit-style facade over httpx.Client used by helper modules."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http
        self.pulls = _Pulls(http)
        self.git = _Git(http)
        self.repos = _Repos(http)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _git_diff(base_ref: str, head_ref: str, *, repo_root: Path) -> str:
    """Return unified diff from origin/base_ref to the working tree.

    GitHub Actions checks out the PR as a detached HEAD (or merge commit),
    so the head ref may not exist as a local branch. Resolve to HEAD when
    the named head ref isn't reachable.
    """
    head = head_ref
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", head_ref],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if probe.returncode != 0:
        head = "HEAD"
    result = subprocess.run(
        ["git", "diff", f"origin/{base_ref}...{head}"],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root,
    )
    return result.stdout


def _git_rev_parse(ref: str, *, repo_root: Path) -> str:
    """Resolve a ref to its commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", ref],
        capture_output=True,
        text=True,
        check=True,
        cwd=repo_root,
    )
    return result.stdout.strip()


def _slack_summary(repo: str, pr_number: int, drift_count: int) -> dict:
    if drift_count == 0:
        text = f":shield: `{repo}#{pr_number}` — 모든 PRD/SEED 요구사항 충족"
    else:
        text = (
            f":shield: `{repo}#{pr_number}` — drift {drift_count}건 감지, "
            f"PR 코멘트 게시됨"
        )
    return {"text": text}


class _AnthropicMessagesAdapter:
    """patcher.ClaudeClient Protocol (has .create) → anthropic SDK shape."""

    def __init__(self, anthropic_client: Any) -> None:
        self._c = anthropic_client

    def create(self, **kwargs: Any) -> Any:
        return self._c.messages.create(**kwargs)


def _maybe_generate_fix_prs(
    *,
    actionable: list[DriftItem],
    octokit: Any,
    owner: str,
    repo_name: str,
    source_pr_number: int,
    repo_root: Path,
    base_ref: str,
    base_sha: str,
    anthropic_key: str,
    max_fixes: int,
) -> list[tuple[DriftItem, int]]:
    """Generate up to ``max_fixes`` fix-PRs from actionable drifts.

    Returns a list of ``(drift, new_pr_number)``. Failures are logged to
    stderr and skipped — never raised, so a flaky fix-PR step can't
    break the primary drift-comment flow.
    """
    # anthropic SDK는 옵션이라 늦은 import (없어도 main flow 정상 동작)
    try:
        from anthropic import Anthropic
    except ImportError:
        print("WARN: anthropic SDK 미설치 → fix-PR 생성 스킵", file=sys.stderr)
        return []

    claude = _AnthropicMessagesAdapter(Anthropic(api_key=anthropic_key))

    seed_md = repo_root / "SEED.md"
    seed_md_text = seed_md.read_text(encoding="utf-8") if seed_md.exists() else ""

    # 코드 패치 컨텍스트는 가벼운 repo overview만 (Claude가 디렉토리 구조로 추론)
    repo_context = _repo_overview(repo_root)

    created: list[tuple[DriftItem, int]] = []
    for drift in actionable[:max_fixes]:
        try:
            if drift.source == "seed":
                proposal = generate_seed_fix(
                    drift, seed_md_text=seed_md_text, client=claude
                )
            elif drift.source == "prd":
                proposal = generate_code_fix_proposal(
                    drift, repo_context=repo_context, client=claude
                )
            else:
                continue
            if proposal is None:
                print(
                    f"[fix-pr] Claude declined: {drift.quote[:50]!r}",
                    file=sys.stderr,
                )
                continue
            branch, pr_num = create_fix_pr(
                octokit,
                owner=owner,
                repo=repo_name,
                drift=drift,
                change=proposal.change,
                rationale=proposal.rationale,
                base_sha=base_sha,
                default_branch=base_ref,
                source_pr_number=source_pr_number,
            )
            print(f"[fix-pr] #{pr_num} ({branch})")
            created.append((drift, pr_num))
        except Exception as e:
            print(f"WARN: fix-PR 생성 실패 ({drift.quote[:30]!r}): {e}", file=sys.stderr)
    return created


def _repo_overview(repo_root: Path, *, max_files: int = 80) -> str:
    """Return a short tree summary so Claude can ground proposals in real paths."""
    paths: list[str] = []
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        paths.append(str(rel))
        if len(paths) >= max_files:
            paths.append(f"... ({len(paths)}+ files truncated)")
            break
    return "\n".join(paths)


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

    if "/" not in args.repo:
        print(f"ERROR: --repo는 owner/name 형식이어야 함: {args.repo}", file=sys.stderr)
        return 2
    owner, repo_name = args.repo.split("/", 1)

    http = create_github_client(gh_token)
    octokit = OctokitAdapter(http)

    # 1) PRD/SEED 존재 여부 → 없으면 onboarding PR 생성 후 종료
    presence = detect_spec_files(args.repo_root)
    if not (presence["prd"] and presence["seed"]):
        base_sha = _git_rev_parse(f"origin/{args.base_ref}", repo_root=args.repo_root)
        result = run_onboarding(
            octokit,
            repo_root=args.repo_root,
            owner=owner,
            repo=repo_name,
            full_name=args.repo,
            default_branch=args.base_ref,
            base_sha=base_sha,
        )
        print(f"[onboarding] {result.status}: {result.reason or ''}")
        if slack_webhook:
            send_slack_webhook(
                slack_webhook,
                {
                    "text": (
                        f":mailbox_with_no_mail: `{args.repo}#{args.pr_number}` — "
                        f"PRD/SEED 없음 → onboarding: {result.status}"
                    )
                },
            )
        return 0

    # 2) Parse PRD + SEED
    spec_bundle = parse_repo(args.repo_root)

    # 3) Extract diff
    raw_diff = _git_diff(args.base_ref, args.head_ref, repo_root=args.repo_root)
    diff = parse_unified_diff(raw_diff)

    # 4) Detect drift → filter actionable → render + post comment
    raw_drifts = detect_drift(spec_bundle, diff)
    actionable, suppressed = filter_actionable_drift(raw_drifts)
    total_reqs = len(spec_bundle.requirements)
    addressed = total_reqs - len(raw_drifts)

    # 4a) Fix-PR 자동 생성 (옵션: ANTHROPIC_API_KEY 설정 시에만)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY") or ""
    max_fixes = int(os.environ.get("PR_GUARD_MAX_FIX_PRS", str(MAX_FIX_PRS_DEFAULT)))
    fix_prs: list[tuple[DriftItem, int]] = []
    if anthropic_key and actionable and max_fixes > 0:
        base_sha = _git_rev_parse(f"origin/{args.base_ref}", repo_root=args.repo_root)
        fix_prs = _maybe_generate_fix_prs(
            actionable=actionable,
            octokit=octokit,
            owner=owner,
            repo_name=repo_name,
            source_pr_number=args.pr_number,
            repo_root=args.repo_root,
            base_ref=args.base_ref,
            base_sha=base_sha,
            anthropic_key=anthropic_key,
            max_fixes=max_fixes,
        )

    footer_parts = [
        f"**Coverage**: {addressed}/{total_reqs} requirements addressed by this PR · "
        f"suppressed {suppressed['unrelated']} unrelated, "
        f"{suppressed['non_goal']} non-goal items (L1 noise reduction).",
    ]
    if fix_prs:
        fix_list = "\n".join(
            f"- #{n} — `{d.source.upper()}:{d.source_file}:{d.line}` "
            f"({'code-fix' if d.source == 'prd' else 'seed-fix'})"
            for d, n in fix_prs
        )
        footer_parts.append(
            f"\n**Auto-generated fix PRs** ({len(fix_prs)}):\n{fix_list}"
        )
    elif anthropic_key and actionable:
        footer_parts.append(
            "\n_(no fix PRs created — Claude declined or generation hit an error; "
            "see Actions logs)_"
        )
    elif actionable and not anthropic_key:
        footer_parts.append(
            "\n_(set `ANTHROPIC_API_KEY` secret to enable auto fix-PR generation)_"
        )
    footer = "\n\n---\n" + "\n".join(footer_parts)

    comment_body = format_drift_comment(actionable) + footer
    publish_pr_comment(
        http,
        owner=owner,
        repo=repo_name,
        pr_number=args.pr_number,
        body=comment_body,
    )
    print(
        f"[drift] raw={len(raw_drifts)} actionable={len(actionable)} "
        f"fix_prs={len(fix_prs)} "
        f"(suppressed unrelated={suppressed['unrelated']}, non_goal={suppressed['non_goal']})"
    )

    # 5) Slack 알림 (실패해도 종료 코드는 0 유지)
    if slack_webhook:
        try:
            send_slack_webhook(
                slack_webhook,
                _slack_summary(args.repo, args.pr_number, len(actionable)),
            )
        except Exception as e:
            print(f"WARN: Slack 알림 실패: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
