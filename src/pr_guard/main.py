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
from .drift import (
    BlockingDriftDecision,
    DriftItem,
    detect_drift,
    filter_actionable_drift,
    partition_coverage_only_drift,
    select_blocking_drift_decisions,
)
from .fix_pr import create_or_reuse_fix_pr
from .github_client import create_github_client
from .guard_report import build_guard_report, write_guard_report
from .llm_provider import LLMProvider, resolve_llm_provider
from .onboarding_orchestrator import run_onboarding
from .publish import publish_pr_comment
from .slack_notify import send_slack_webhook
from .spec_parser import parse_repo


MAX_FIX_PRS_DEFAULT = 3
PR_COMMENT_MARKER = "<!-- pr-guard:drift-report -->"


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
        r = self._http.get(
            f"/repos/{owner}/{repo}/pulls", params={"state": state, "per_page": 100}
        )
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
        if "sha" not in body:
            existing = self._http.get(
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": body.get("branch")},
            )
            if existing.status_code == 200:
                existing_payload = existing.json()
                if isinstance(existing_payload, dict) and existing_payload.get("sha"):
                    body["sha"] = existing_payload["sha"]
            elif existing.status_code != 404:
                existing.raise_for_status()
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


def _published_comment_url(
    published_comment: Any,
    *,
    repo: str,
    pr_number: int,
) -> str | None:
    """Return a stable GitHub URL for the PR Guard comment when available."""
    if not isinstance(published_comment, dict):
        return None

    html_url = str(published_comment.get("html_url") or "").strip()
    if html_url.startswith("https://") or html_url.startswith("http://"):
        return html_url

    comment_id = published_comment.get("id")
    if comment_id is None:
        return None
    return f"https://github.com/{repo}/pull/{pr_number}#issuecomment-{comment_id}"


def _slack_summary(
    repo: str,
    pr_number: int,
    drift_count: int,
    *,
    comment_url: str | None = None,
) -> dict:
    comment_label = f"<{comment_url}|PR 코멘트>" if comment_url else "PR 코멘트"
    if drift_count == 0:
        text = (
            f":shield: `{repo}#{pr_number}` — 모든 PRD/SEED 요구사항 충족, "
            f"{comment_label} 게시됨"
        )
    else:
        text = (
            f":shield: `{repo}#{pr_number}` — drift {drift_count}건 감지, "
            f"{comment_label} 게시됨"
        )
    return {"text": text}


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
    provider: LLMProvider,
    max_fixes: int,
) -> list[dict[str, Any]]:
    """Generate up to ``max_fixes`` fix-PRs from actionable drifts.

    Returns fix-PR result dicts with status/branch/reason. Failures are logged
    to stderr and skipped — never raised, so a flaky fix-PR step can't break
    the primary drift-comment flow.
    """
    seed_md = repo_root / "SEED.md"
    seed_md_text = seed_md.read_text(encoding="utf-8") if seed_md.exists() else ""

    # 코드 패치 컨텍스트는 가벼운 repo overview만 (Claude가 디렉토리 구조로 추론)
    repo_context = _repo_overview(repo_root)

    created: list[dict[str, Any]] = []
    for drift in actionable[:max_fixes]:
        try:
            if drift.source == "seed":
                proposal = provider.generate_seed_fix(drift, seed_md_text=seed_md_text)
            elif drift.source == "prd":
                proposal = provider.generate_code_fix_proposal(
                    drift, repo_context=repo_context
                )
            else:
                continue
            if proposal is None:
                print(
                    f"[fix-pr] provider declined: {drift.quote[:50]!r}",
                    file=sys.stderr,
                )
                continue
            result = create_or_reuse_fix_pr(
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
            pr_num = result.get("pr_number")
            branch = result.get("branch")
            status = result.get("status")
            reason = result.get("reason")
            if pr_num is None:
                print(f"[fix-pr] {status} ({branch}): {reason}", file=sys.stderr)
            else:
                print(f"[fix-pr] {status} #{pr_num} ({branch}): {reason}")
            created.append(result)
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


def _diff_summary_for_semantic_blocking(diff: Any, *, max_chars: int = 4000) -> str:
    """Compact diff context for the semantic blocking classifier."""
    lines: list[str] = []
    for file in diff.files[:12]:
        lines.append(
            f"FILE {file.path} ({file.change_type}, +{file.added_lines}, -{file.removed_lines})"
        )
        if file.added_symbols:
            lines.append("symbols: " + ", ".join(file.added_symbols[:20]))
        added = file.added_text.strip()
        if added:
            lines.append("added:")
            lines.append(added[:800])
        lines.append("")

    if len(diff.files) > 12:
        lines.append(f"... {len(diff.files) - 12} more file(s) omitted")

    summary = "\n".join(lines).strip()
    return summary[:max_chars]


def _format_fix_pr_result(item: tuple[DriftItem, int] | dict[str, Any]) -> str:
    if isinstance(item, dict):
        drift = item.get("drift")
        pr_number = item.get("pr_number")
        status = item.get("status", "created")
        branch = item.get("branch")
        reason = item.get("reason")
    else:
        drift, pr_number = item
        status = "created"
        branch = None
        reason = None

    if isinstance(drift, DriftItem):
        source = drift.source
        source_file = drift.source_file
        line_no = drift.line
    elif isinstance(drift, dict):
        source = str(drift.get("source", "spec"))
        source_file = str(drift.get("source_file", "unknown"))
        line_no = drift.get("line", "?")
    else:
        source = "spec"
        source_file = "unknown"
        line_no = "?"

    kind = "code-fix" if source == "prd" else "seed-fix"
    pr_label = f"#{pr_number}" if pr_number is not None else "no PR"
    parts = [
        f"- {pr_label} — `{source.upper()}:{source_file}:{line_no}` ({kind}; {status})"
    ]
    if branch:
        parts.append(f"branch `{branch}`")
    if reason:
        parts.append(str(reason))
    return " — ".join(parts)


def _format_blocking_reasons(decisions: list[BlockingDriftDecision]) -> str:
    semantic = [decision for decision in decisions if decision.source == "semantic"]
    if not semantic:
        return ""
    lines = ["\n**Semantic blocking evidence:**"]
    for decision in semantic[:5]:
        drift = decision.drift
        loc = f"{drift.source_file}:{drift.line}"
        reason = decision.reason.strip() or "Classified as blocking by semantic provider."
        lines.append(f"- `{loc}` — {reason}")
    if len(semantic) > 5:
        lines.append(f"- ... {len(semantic) - 5} more blocking item(s)")
    return "\n".join(lines)


def _fix_pr_ready_count(fix_prs: list[tuple[DriftItem, int] | dict[str, Any]]) -> int:
    count = 0
    for item in fix_prs:
        if isinstance(item, dict):
            if item.get("pr_number") is not None:
                count += 1
        else:
            count += 1
    return count


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
    parser.add_argument("--json-output", type=Path, help="Write structured guard report JSON")
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Dry-run gate mode: skip GitHub/Slack/onboarding/fix-PR side effects",
    )
    parser.add_argument(
        "--publish-best-effort",
        action="store_true",
        help="Continue after PR comment publishing fails; keep JSON artifact/check verdict authoritative",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="Return nonzero when the structured report verdict is not pass",
    )
    parser.add_argument(
        "--fail-on-advisory-drift",
        action="store_true",
        help=(
            "Legacy strict mode: treat every advisory (token-coverage) drift item "
            "as blocking. Off by default because static partial matches are noisy "
            "and produce false-positive CI failures; advisory drift is otherwise "
            "reported in the PR comment without failing the check."
        ),
    )
    args = parser.parse_args(argv)

    gh_token = os.environ.get("GITHUB_TOKEN")
    slack_webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not gh_token and not args.no_publish:
        print("ERROR: GITHUB_TOKEN env var 필요", file=sys.stderr)
        return 1

    if "/" not in args.repo:
        print(f"ERROR: --repo는 owner/name 형식이어야 함: {args.repo}", file=sys.stderr)
        return 2
    owner, repo_name = args.repo.split("/", 1)

    http = create_github_client(gh_token) if gh_token and not args.no_publish else None
    octokit = OctokitAdapter(http) if http is not None else None

    # 1) PRD/SEED 존재 여부 → 없으면 onboarding PR 생성 후 종료
    presence = detect_spec_files(args.repo_root)
    if not (presence["prd"] and presence["seed"]):
        if args.no_publish:
            report = build_guard_report(
                repo=args.repo,
                pr_number=args.pr_number,
                actionable_drifts=[],
                fix_prs=[],
                suppressed={"unrelated": 0, "non_goal": 0},
            )
            report["summary"] = "PRD/SEED missing; onboarding side effects skipped by --no-publish."
            if args.json_output:
                write_guard_report(report, args.json_output)
            print("[onboarding] skipped: PRD/SEED missing (--no-publish)")
            return 0 if not args.fail_on_drift or report["verdict"] == "pass" else 1

        if octokit is None:
            print("ERROR: GitHub client unavailable for onboarding", file=sys.stderr)
            return 1
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

    # 4) Detect drift → scope-filter coverage-only PRs → filter actionable →
    #    render + post comment.
    raw_drifts = detect_drift(spec_bundle, diff)
    # A tests/docs-only PR introduces no implementation, so unmet 성공 기준/핵심
    # 제약 are coverage, not drift (PRD/SEED non-goal rule). Strip those before
    # actionable filtering so they never reach the semantic classifier or fail
    # the check. Source-touching PRs are unaffected — see partition docstring.
    raw_drifts, coverage_only_suppressed = partition_coverage_only_drift(raw_drifts, diff)
    advisory, suppressed = filter_actionable_drift(raw_drifts)

    provider_metadata = {
        "repo": args.repo,
        "pr_number": args.pr_number,
        "base_ref": args.base_ref,
        "head_ref": args.head_ref,
        "head_sha": os.environ.get("GITHUB_SHA"),
    }
    provider = (
        None
        if args.no_publish
        else resolve_llm_provider(os.environ, metadata=provider_metadata)
    )
    blocking_decisions = select_blocking_drift_decisions(
        advisory,
        fail_on_advisory=args.fail_on_advisory_drift,
        provider=provider,
        diff_summary=_diff_summary_for_semantic_blocking(diff),
    )
    blocking = [decision.drift for decision in blocking_decisions]
    total_reqs = len(spec_bundle.requirements)
    addressed = total_reqs - len(raw_drifts)

    # 4a) Fix-PR 자동 생성 (Hermes webhook preferred; Anthropic fallback)
    max_fixes = int(os.environ.get("PR_GUARD_MAX_FIX_PRS", str(MAX_FIX_PRS_DEFAULT)))
    fix_prs: list[Any] = []
    if provider is not None and advisory and max_fixes > 0 and octokit is not None:
        base_sha = _git_rev_parse(f"origin/{args.base_ref}", repo_root=args.repo_root)
        fix_prs = _maybe_generate_fix_prs(
            actionable=advisory,
            octokit=octokit,
            owner=owner,
            repo_name=repo_name,
            source_pr_number=args.pr_number,
            repo_root=args.repo_root,
            base_ref=args.base_ref,
            base_sha=base_sha,
            provider=provider,
            max_fixes=max_fixes,
        )

    footer_parts = [
        f"**Coverage**: {addressed}/{total_reqs} requirements addressed by this PR · "
        f"suppressed {suppressed['unrelated']} unrelated, "
        f"{suppressed['non_goal']} non-goal items (L1 noise reduction).",
    ]
    if coverage_only_suppressed:
        footer_parts.append(
            f"\n_(scope: coverage-only PR — every changed file is a test or doc, so "
            f"{len(coverage_only_suppressed)} unmet 성공 기준/핵심 제약 were treated as "
            "coverage of already-merged implementation, not drift.)_"
        )
    if advisory and not blocking:
        footer_parts.append(
            "\n_(advisory only — these are static token-coverage findings and do "
            "**not** fail the check. Run with `--fail-on-advisory-drift` to block "
            "on them.)_"
        )
    elif blocking:
        if args.fail_on_advisory_drift:
            footer_parts.append(
                f"\n_(strict advisory mode promoted {len(blocking)} drift item(s) "
                "to blocking.)_"
            )
        else:
            footer_parts.append(
                f"\n_(semantic classifier marked {len(blocking)} advisory drift item(s) "
                "as blocking.)_"
            )
            blocking_reasons = _format_blocking_reasons(blocking_decisions)
            if blocking_reasons:
                footer_parts.append(blocking_reasons)
    if advisory and provider is None:
        footer_parts.append(
            "\n_(no LLM provider configured; semantic blocking classification was skipped, "
            "so advisory drift remains non-blocking. Set `HERMES_PR_GUARD_WEBHOOK_URL` "
            "(preferred) or `ANTHROPIC_API_KEY` to enable semantic blocking.)_"
        )
    if fix_prs:
        fix_list = "\n".join(_format_fix_pr_result(item) for item in fix_prs)
        ready_count = _fix_pr_ready_count(fix_prs)
        skipped_count = len(fix_prs) - ready_count
        footer_parts.append(
            "\n**Auto-generated fix PR handling** "
            f"({ready_count} ready/reused, {skipped_count} skipped):\n{fix_list}"
        )
    elif advisory and max_fixes <= 0:
        footer_parts.append(
            "\n_(auto fix-PR generation disabled by `PR_GUARD_MAX_FIX_PRS=0`; "
            "JSON report/comment only)_"
        )
    elif provider is not None and advisory:
        footer_parts.append(
            "\n_(no fix PRs created — LLM provider declined or generation hit an error; "
            "see Actions logs)_"
        )
    footer = "\n\n---\n" + "\n".join(footer_parts)

    report = build_guard_report(
        repo=args.repo,
        pr_number=args.pr_number,
        actionable_drifts=advisory,
        fix_prs=fix_prs,
        suppressed=suppressed,
        blocking_drifts=blocking_decisions,
    )
    if args.json_output:
        write_guard_report(report, args.json_output)

    comment_body = format_drift_comment(advisory) + footer
    published_comment_url: str | None = None
    if not args.no_publish and http is not None:
        try:
            published_comment = publish_pr_comment(
                http,
                owner=owner,
                repo=repo_name,
                pr_number=args.pr_number,
                body=comment_body,
                marker=PR_COMMENT_MARKER,
            )
            published_comment_url = _published_comment_url(
                published_comment,
                repo=args.repo,
                pr_number=args.pr_number,
            )
        except Exception as e:
            if not args.publish_best_effort:
                raise
            print(
                "WARN: PR comment publish failed; continuing because "
                f"--publish-best-effort is set: {e}",
                file=sys.stderr,
            )
    print(
        f"[drift] raw={len(raw_drifts)} advisory={len(advisory)} "
        f"blocking={len(blocking)} fix_prs={len(fix_prs)} "
        f"coverage_only_suppressed={len(coverage_only_suppressed)} "
        f"(suppressed unrelated={suppressed['unrelated']}, non_goal={suppressed['non_goal']})"
    )

    # 5) Slack 알림 (실패해도 종료 코드는 0 유지)
    if slack_webhook and not args.no_publish:
        try:
            send_slack_webhook(
                slack_webhook,
                _slack_summary(
                    args.repo,
                    args.pr_number,
                    len(advisory),
                    comment_url=published_comment_url,
                ),
            )
        except Exception as e:
            print(f"WARN: Slack 알림 실패: {e}", file=sys.stderr)

    if args.fail_on_drift and report["verdict"] != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
