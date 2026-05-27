# Hermes-backed PR Guard Gate Implementation Plan

> **For Hermes:** Implement with TDD. Keep GitHub Actions as the deterministic gate and Hermes as the optional semantic/fix provider.

**Goal:** Make pr-guard usable as a required PR consistency gate while allowing LLM/fix generation through Hermes instead of a direct Anthropic API key.

**Architecture:** Add a structured report object that can be emitted as JSON and used as a CI verdict. Add a provider abstraction for fix proposal generation: Hermes webhook first, Anthropic direct only as fallback. Keep the current static matcher as the local/offline baseline; do not require Ouroboros for the GitHub Action path.

**Tech Stack:** Python 3.12, pytest, httpx, GitHub Actions.

---

## Task 1: Structured guard report and CI verdict

- Add `src/pr_guard/guard_report.py` with report dataclasses/functions.
- Add tests in `tests/test_guard_report.py`.
- Report fields: `schema_version`, `repo`, `pr_number`, `verdict`, `drift_count`, `fix_pr_count`, `drifts`, `fix_prs`, `suppressed`, `summary`.
- Verdict rules: `pass` if no actionable drift; `fail` if actionable drift remains; `needs_fix_review` if fix PRs were generated.

## Task 2: CLI JSON/no-publish/fail-on-drift mode

- Extend `main.py` flags: `--json-output`, `--no-publish`, `--fail-on-drift`.
- In no-publish mode, skip PR comment, Slack, fix PR creation side effects unless explicitly allowed.
- In publish mode, update the existing marker-based PR comment instead of creating comment noise on every push.
- If JSON output path is given, write the structured report.
- If `--fail-on-drift`, return nonzero when report verdict is not `pass`.

## Task 3: Hermes LLM provider abstraction

- Add `src/pr_guard/llm_provider.py`.
- Provider resolution:
  - `HERMES_PR_GUARD_WEBHOOK_URL` → Hermes webhook provider
  - optional `HERMES_PR_GUARD_WEBHOOK_TOKEN` → Bearer auth header
  - else `ANTHROPIC_API_KEY` → Anthropic provider fallback
  - else no provider
- Hermes provider sends drift context to Hermes webhook/API endpoint and parses the same JSON proposal shape as `patcher.py`.
- Refactor `main.py` so it no longer imports Anthropic directly.

## Task 4: GitHub Action and docs

- Update workflow to use `pr-guard --json-output pr-guard-report.json --fail-on-drift`.
- Document required secrets/env:
  - `SLACK_WEBHOOK_URL` points to Slack channel C0B6XNQCYFJ in current DS setup.
  - `HERMES_PR_GUARD_WEBHOOK_URL` optional, preferred over Anthropic API key.
  - `HERMES_PR_GUARD_WEBHOOK_TOKEN` optional, protects the Hermes endpoint.
- Document branch-protection setup: make workflow job `PR Guard` a required status check.
- Document that Ouroboros exists in DS runtime but is not required in the Action path; use it behind Hermes if needed for deeper semantic review.

## Task 5: Verification

- Run targeted tests for new modules.
- Run full suite.
- Run a local CLI no-publish JSON smoke test if feasible.
