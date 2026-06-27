from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pr_guard import main as main_mod
from pr_guard.drift import BlockingDriftDecision, DriftItem
from pr_guard.review import ReviewFinding, ReviewReport
from pr_guard.spec_parser import SpecBundle


def _drift() -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source="prd",
        source_file="PRD.md",
        section="Acceptance",
        kind="acceptance",
        quote="implement required webhook flow",
        line=20,
        score=0.5,
    )


def _install_common_stubs(monkeypatch: Any, actionable: list[DriftItem]) -> dict[str, int]:
    calls = {"github": 0, "publish": 0, "slack": 0, "fix_prs": 0}
    suppressed = {"unrelated": 1, "non_goal": 0}

    monkeypatch.setattr(
        main_mod,
        "detect_spec_files",
        lambda repo_root: {"prd": True, "seed": True},
    )
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: actionable)
    monkeypatch.setattr(main_mod, "filter_actionable_drift", lambda raw: (actionable, suppressed))

    def fail_github(*args: Any, **kwargs: Any) -> None:
        calls["github"] += 1
        raise AssertionError("GitHub client should not be created in --no-publish mode")

    def record_publish(*args: Any, **kwargs: Any) -> None:
        calls["publish"] += 1
        raise AssertionError("PR comment should not be published in --no-publish mode")

    def record_slack(*args: Any, **kwargs: Any) -> None:
        calls["slack"] += 1
        raise AssertionError("Slack should not be called in --no-publish mode")

    def record_fix_prs(*args: Any, **kwargs: Any) -> list[tuple[DriftItem, int]]:
        calls["fix_prs"] += 1
        raise AssertionError("Fix PRs should not be created in --no-publish mode")

    monkeypatch.setattr(main_mod, "create_github_client", fail_github)
    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)
    monkeypatch.setattr(main_mod, "send_slack_webhook", record_slack)
    monkeypatch.setattr(main_mod, "_maybe_generate_fix_prs", record_fix_prs)
    return calls


def _install_publish_stubs(
    monkeypatch: Any,
    *,
    provider: Any | None,
    actionable: list[DriftItem] | None = None,
) -> list[dict[str, Any]]:
    items = actionable or []
    published: list[dict[str, Any]] = []

    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("PR_GUARD_MAX_FIX_PRS", "0")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        main_mod,
        "detect_spec_files",
        lambda repo_root: {"prd": True, "seed": True},
    )
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: items)
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: (items, {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())
    monkeypatch.setattr(main_mod, "resolve_llm_provider", lambda env, **kwargs: provider)

    def record_publish(*args: Any, **kwargs: Any) -> dict[str, int]:
        published.append(dict(kwargs))
        return {"id": 123}

    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)
    return published


def _review_report(
    *,
    score: int = 4,
    findings: tuple[ReviewFinding, ...] = (),
    summary: str = "Review pass completed.",
) -> ReviewReport:
    return ReviewReport(findings=findings, score=score, summary=summary)


def _security_finding() -> ReviewFinding:
    return ReviewFinding(
        category="security",
        severity="error",
        file="src/auth.py",
        line=44,
        quote="token",
        suggestion="Validate the token before use.",
    )


def test_slack_summary_links_to_published_pr_comment() -> None:
    payload = main_mod._slack_summary(
        "octo/app",
        42,
        3,
        comment_url="https://github.com/octo/app/pull/42#issuecomment-123",
    )

    assert payload == {
        "text": (
            ":shield: `octo/app#42` — drift 3건 감지, "
            "<https://github.com/octo/app/pull/42#issuecomment-123|PR 코멘트> 게시됨"
        )
    }


def test_published_comment_url_falls_back_to_comment_id() -> None:
    assert (
        main_mod._published_comment_url({"id": 123}, repo="octo/app", pr_number=42)
        == "https://github.com/octo/app/pull/42#issuecomment-123"
    )


def test_no_publish_fails_only_when_advisory_drift_is_promoted_to_blocking(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example/hook")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    calls = _install_common_stubs(monkeypatch, [_drift()])
    output = tmp_path / "pr-guard-report.json"

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--no-publish",
            "--fail-on-drift",
            "--fail-on-advisory-drift",
        ]
    )

    assert rc == 1
    assert calls == {"github": 0, "publish": 0, "slack": 0, "fix_prs": 0}
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "fail"
    assert report["drift_count"] == 1
    assert report["blocking_count"] == 1
    assert report["suppressed"] == {"unrelated": 1, "non_goal": 0}


def test_no_publish_advisory_drift_is_non_blocking_by_default(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # The core false-positive fix: a static token-coverage drift item is
    # surfaced (drift_count == 1) but does NOT fail the check by default.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _install_common_stubs(monkeypatch, [_drift()])
    output = tmp_path / "pr-guard-report.json"

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--no-publish",
            "--fail-on-drift",
        ]
    )

    assert rc == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert report["drift_count"] == 1
    assert report["blocking_count"] == 0


def test_provider_semantic_blocking_fails_gate_without_fix_prs(
    tmp_path: Path, monkeypatch: Any
) -> None:
    drift = _drift()
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("PR_GUARD_MAX_FIX_PRS", "0")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        main_mod,
        "detect_spec_files",
        lambda repo_root: {"prd": True, "seed": True},
    )
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [drift])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([drift], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())

    class Provider:
        def classify_blocking_drift(self, items, *, diff_summary=None):
            assert diff_summary == ""
            return [
                BlockingDriftDecision(
                    drift=items[0],
                    reason="Webhook code path changed but signature verification remains absent.",
                )
            ]

    monkeypatch.setattr(main_mod, "resolve_llm_provider", lambda env, **kwargs: Provider())
    published: dict[str, str] = {}
    output = tmp_path / "pr-guard-report.json"

    def record_publish(*args: Any, **kwargs: Any) -> None:
        published["body"] = kwargs["body"]

    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--fail-on-drift",
        ]
    )

    assert rc == 1
    assert "semantic classifier marked 1 advisory drift item" in published["body"]
    assert "Webhook code path changed" in published["body"]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "fail"
    assert report["drift_count"] == 1
    assert report["blocking_count"] == 1
    assert report["blocking_drifts"][0]["reason"].startswith("Webhook code path")


def test_missing_provider_key_keeps_advisory_drift_green(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("PR_GUARD_MAX_FIX_PRS", "0")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HERMES_PR_GUARD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main_mod, "detect_spec_files", lambda repo_root: {"prd": True, "seed": True})
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [_drift()])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([_drift()], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())
    published: dict[str, str] = {}
    output = tmp_path / "pr-guard-report.json"

    def record_publish(*args: Any, **kwargs: Any) -> None:
        published["body"] = kwargs["body"]

    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--fail-on-drift",
        ]
    )

    assert rc == 0
    assert "semantic blocking classification was skipped" in published["body"]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert report["blocking_count"] == 0


def test_no_publish_pass_report_returns_zero_with_fail_on_drift(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    _install_common_stubs(monkeypatch, [])
    output = tmp_path / "pr-guard-report.json"

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--no-publish",
            "--fail-on-drift",
        ]
    )

    assert rc == 0
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "pass"


def test_slack_notification_includes_published_comment_url(
    tmp_path: Path, monkeypatch: Any
) -> None:
    drift = _drift()
    comment_url = "https://github.com/octo/app/pull/42#issuecomment-123"
    slack_payload: dict[str, Any] = {}
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.example/hook")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_PR_GUARD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(main_mod, "detect_spec_files", lambda repo_root: {"prd": True, "seed": True})
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [drift])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([drift], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())
    monkeypatch.setattr(
        main_mod,
        "publish_pr_comment",
        lambda *args, **kwargs: {"id": 123, "html_url": comment_url},
    )

    def record_slack(webhook_url: str, payload: dict[str, Any]) -> int:
        slack_payload.update(payload)
        return 200

    monkeypatch.setattr(main_mod, "send_slack_webhook", record_slack)

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert f"<{comment_url}|PR 코멘트>" in slack_payload["text"]


def test_publish_best_effort_keeps_report_when_comment_publish_fails(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("HERMES_PR_GUARD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(main_mod, "detect_spec_files", lambda repo_root: {"prd": True, "seed": True})
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())

    def fail_publish(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Resource not accessible by integration")

    monkeypatch.setattr(main_mod, "publish_pr_comment", fail_publish)
    output = tmp_path / "pr-guard-report.json"

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--publish-best-effort",
            "--fail-on-drift",
        ]
    )

    assert rc == 0
    assert json.loads(output.read_text(encoding="utf-8"))["verdict"] == "pass"
    assert "--publish-best-effort" in capsys.readouterr().err


def test_max_fix_prs_zero_explains_fix_generation_is_disabled(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("PR_GUARD_MAX_FIX_PRS", "0")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(main_mod, "detect_spec_files", lambda repo_root: {"prd": True, "seed": True})
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [_drift()])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([_drift()], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())
    monkeypatch.setattr(main_mod, "resolve_llm_provider", lambda env, **kwargs: object())
    published: dict[str, str] = {}

    def record_publish(*args: Any, **kwargs: Any) -> None:
        published["body"] = kwargs["body"]

    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert "PR_GUARD_MAX_FIX_PRS=0" in published["body"]


def test_fix_pr_footer_includes_idempotent_status_reason_and_fail_on_drift_still_fails(
    tmp_path: Path, monkeypatch: Any
) -> None:
    drift = _drift()
    monkeypatch.setenv("GITHUB_TOKEN", "dummy-token")
    monkeypatch.setenv("PR_GUARD_MAX_FIX_PRS", "1")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(main_mod, "detect_spec_files", lambda repo_root: {"prd": True, "seed": True})
    monkeypatch.setattr(
        main_mod,
        "parse_repo",
        lambda repo_root: SpecBundle(
            prd_path="PRD.md",
            seed_path="SEED.md",
            seed_yaml_path=None,
            requirements=[],
        ),
    )
    monkeypatch.setattr(main_mod, "_git_diff", lambda base_ref, head_ref, repo_root: "")
    monkeypatch.setattr(main_mod, "detect_drift", lambda spec_bundle, diff: [drift])
    monkeypatch.setattr(
        main_mod,
        "filter_actionable_drift",
        lambda raw: ([drift], {"unrelated": 0, "non_goal": 0}),
    )
    monkeypatch.setattr(main_mod, "create_github_client", lambda token: object())
    monkeypatch.setattr(main_mod, "resolve_llm_provider", lambda env, **kwargs: object())
    monkeypatch.setattr(main_mod, "_git_rev_parse", lambda ref, repo_root: "base-sha")
    monkeypatch.setattr(
        main_mod,
        "_maybe_generate_fix_prs",
        lambda **kwargs: [
            {
                "drift": drift,
                "status": "reused",
                "branch": "pr-guard/code-fix/prd-webhook-flow-1234abcd",
                "pr_number": 99,
                "reason": "existing open PR #99 already uses branch; reused instead",
            }
        ],
    )
    published: dict[str, str] = {}
    output = tmp_path / "pr-guard-report.json"

    def record_publish(*args: Any, **kwargs: Any) -> None:
        published["body"] = kwargs["body"]

    monkeypatch.setattr(main_mod, "publish_pr_comment", record_publish)

    # The idempotent fix-PR path may reuse an existing proposal, but
    # --fail-on-drift must still fail the GitHub Actions check whenever
    # actionable drift remains and the report verdict is not pass.
    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--json-output",
            str(output),
            "--fail-on-drift",
        ]
    )

    assert rc == 1
    assert "reused" in published["body"]
    assert "existing open PR #99" in published["body"]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["verdict"] == "needs_fix_review"
    assert report["drift_count"] == 1


def test_review_flag_runs_provider_and_publishes_review_comment(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls: list[dict[str, str]] = []

    class Provider:
        def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport:
            calls.append({"diff_summary": diff_summary, "repo_context": repo_context})
            return _review_report(score=4)

    published = _install_publish_stubs(monkeypatch, provider=Provider())

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--review",
        ]
    )

    assert rc == 0
    assert calls == [{"diff_summary": "", "repo_context": ""}]
    assert [item["marker"] for item in published] == [
        main_mod.PR_COMMENT_MARKER,
        main_mod.REVIEW_COMMENT_MARKER,
    ]
    assert "## PR Guard — Review" in published[1]["body"]


def test_fail_on_security_sets_nonzero_exit(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    class Provider:
        def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport:
            return _review_report(score=2, findings=(_security_finding(),))

    _install_publish_stubs(monkeypatch, provider=Provider())

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--review",
            "--fail-on-security",
        ]
    )

    assert rc == 1
    assert "[review] score=2 findings=1 security_blocking=True" in capsys.readouterr().out


def test_unknown_review_score_does_not_fail_security_gate(
    tmp_path: Path, monkeypatch: Any
) -> None:
    class Provider:
        def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport:
            return _review_report(score=-1, findings=())

    published = _install_publish_stubs(monkeypatch, provider=Provider())

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--review",
            "--fail-on-security",
        ]
    )

    assert rc == 0
    assert "**Score: unknown**" in published[1]["body"]


def test_review_pass_skips_without_provider(tmp_path: Path, monkeypatch: Any) -> None:
    published = _install_publish_stubs(monkeypatch, provider=None)

    rc = main_mod.main(
        [
            "--repo",
            "octo/app",
            "--pr-number",
            "42",
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--repo-root",
            str(tmp_path),
            "--review",
            "--fail-on-security",
        ]
    )

    assert rc == 0
    assert [item["marker"] for item in published] == [main_mod.PR_COMMENT_MARKER]
