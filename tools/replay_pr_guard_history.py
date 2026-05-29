#!/usr/bin/env python3
"""Replay pr-guard drift decisions over recent repository commits.

This is a dogfood QA helper: it runs the current pr-guard matcher against this
repo's recent commit diffs and verifies the provider-less default mode stays
green. Strict advisory mode is reported for visibility, but does not determine
the exit code unless ``--fail-on-strict`` is supplied.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pr_guard.diff_extractor import parse_unified_diff
from pr_guard.drift import detect_drift, filter_actionable_drift, select_blocking_drift
from pr_guard.spec_parser import parse_repo


@dataclass(frozen=True)
class ReplayRow:
    commit: str
    subject: str
    advisory: int
    blocking: int
    strict: int
    suppressed: dict[str, int]


@dataclass(frozen=True)
class ReplaySummary:
    rows: list[ReplayRow]
    default_failures: int
    strict_failures: int
    advisory_total: int


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root to replay (default: cwd).",
    )
    parser.add_argument(
        "--commits",
        type=int,
        default=12,
        help="Number of recent commits to replay (default: 12).",
    )
    parser.add_argument(
        "--fail-on-strict",
        action="store_true",
        help="Also fail when legacy strict advisory mode would block.",
    )
    args = parser.parse_args(argv)

    summary = replay_history(repo_root=args.repo_root, commit_count=args.commits)
    print(format_summary(summary))

    if summary.default_failures:
        return 1
    if args.fail_on_strict and summary.strict_failures:
        return 1
    return 0


def replay_history(*, repo_root: Path, commit_count: int) -> ReplaySummary:
    repo_root = repo_root.resolve()
    spec = parse_repo(repo_root)
    commits = _git(
        ["rev-list", f"--max-count={commit_count}", "HEAD"],
        cwd=repo_root,
    ).splitlines()

    rows: list[ReplayRow] = []
    default_failures = 0
    strict_failures = 0
    advisory_total = 0

    for commit in reversed(commits):
        parents = _git(["rev-list", "--parents", "-n", "1", commit], cwd=repo_root).split()
        if len(parents) < 2:
            continue

        raw_diff = _git(["diff", f"{parents[1]}...{commit}"], cwd=repo_root)
        diff = parse_unified_diff(raw_diff)
        raw_drifts = detect_drift(spec, diff)
        advisory, suppressed = filter_actionable_drift(raw_drifts)
        blocking = select_blocking_drift(advisory, provider=None)
        strict_blocking = select_blocking_drift(advisory, fail_on_advisory=True)

        default_failures += 1 if blocking else 0
        strict_failures += 1 if strict_blocking else 0
        advisory_total += len(advisory)

        label = _git(["show", "-s", "--format=%h%x00%s", commit], cwd=repo_root)
        short_sha, subject = label.split("\x00", 1)
        rows.append(
            ReplayRow(
                commit=short_sha,
                subject=subject,
                advisory=len(advisory),
                blocking=len(blocking),
                strict=len(strict_blocking),
                suppressed=suppressed,
            )
        )

    return ReplaySummary(
        rows=rows,
        default_failures=default_failures,
        strict_failures=strict_failures,
        advisory_total=advisory_total,
    )


def format_summary(summary: ReplaySummary) -> str:
    lines = ["pr-guard history replay"]
    for row in summary.rows:
        lines.append(
            f"- {row.commit} {row.subject}: "
            f"advisory={row.advisory} "
            f"blocking={row.blocking} "
            f"strict={row.strict} "
            f"suppressed={row.suppressed}"
        )
    lines.append(
        "summary: "
        f"commits={len(summary.rows)} "
        f"default_failures={summary.default_failures} "
        f"strict_failures={summary.strict_failures} "
        f"advisory_total={summary.advisory_total}"
    )
    return "\n".join(lines)


def _git(args: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
