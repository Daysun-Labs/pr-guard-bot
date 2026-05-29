# PR Guard evaluate readiness - 2026-05-29

This packet is the public, transcript-visible evidence bundle for rerunning
`ooo evaluate` against `SEED.yaml`. It intentionally avoids live adapter URLs,
tokens, Slack message bodies, private hostnames, and other DS operational
internals.

## Summary

- Current readiness: mechanically green; the public readiness packet is assembled;
  30-day adoption is still an observation criterion rather than a completed
  release criterion.
- Latest mechanical proof:
  - `.venv/bin/pytest` -> 239 passed, 1 warning.
  - `uv run --extra dev pytest` -> 239 passed, 1 warning.
  - `uv run --extra dev --extra adapter pytest` -> 239 passed, 1 warning.
  - `.venv/bin/python -m compileall -q src tests adapter` -> exit 0.
  - Focused evidence suite covering latency, comments/reports, Hermes provider,
    fix PR routing, adapter validation, onboarding, public workflow safety, and
    semantic blocking -> 92 passed.
- Known warning: `StarletteDeprecationWarning` from `fastapi.testclient`; it does
  not fail the suite.

## Live PR / Slack evidence

The SEED criterion "pull_request opened/synchronize event -> PR Guard GitHub
Actions check and Slack notification within 5 minutes" has current evidence:

- PR: <https://github.com/Daysun-Labs/pr-guard-bot/pull/26>
- Workflow run: <https://github.com/Daysun-Labs/pr-guard-bot/actions/runs/26614974424>
- Event: `pull_request`
- Run created: 2026-05-29T02:49:08Z
- PR Guard check started: 2026-05-29T02:49:12Z
- PR Guard check completed: 2026-05-29T02:49:33Z, conclusion `SUCCESS`
- Stable PR Guard comment posted: 2026-05-29T02:49:29Z
- Elapsed created -> check success: 25 seconds
- Slack delivery: confirmed by the operator in the evaluation thread on
  2026-05-29; exact Slack content/permalink is intentionally kept out of this
  public repo packet.
- This operator confirmation is the transcript-visible Slack evidence for this
  public packet; excluding private Slack content is intentional, not a missing
  artifact.

## Acceptance-criteria evidence map

Status labels:

- `proven`: live GitHub/operator evidence exists in this packet.
- `test-proven`: covered by deterministic local tests and mechanical proof.
- `approval-gated`: repo-side behavior is proven, but live external side effects
  remain disabled until explicitly approved.
- `observing`: long-running operational criterion is being tracked but is not
  complete.

| SEED AC | Evidence status | Current evidence |
| --- | --- | --- |
| 1. PR event produces PR Guard check + Slack within 5 minutes | `proven` | PR #26 Actions run completed successfully in 25 seconds; PR Guard comment posted; Slack delivery operator-confirmed. Unit coverage: `tests/test_e2e_latency.py`. |
| 2. Advisory drift creates comment + JSON but is non-blocking by default; blocking drift fails | `proven` / `test-proven` | `tests/test_main_cli_gate.py`, `tests/test_guard_report.py`, `tests/test_comment_format.py`, `tests/test_publish.py`, and PR #26 comment showing stable marker report. |
| 3. PRD drift can generate Hermes code-fix proposal | `test-proven` / `approval-gated` | `tests/test_llm_provider.py::test_hermes_code_fix_posts_context_and_parses_nested_proposal`, `tests/test_fix_pr.py::test_prd_drift_routes_to_code_fix_branch_prefix`, `adapter/tests/test_service.py::test_code_fix_request_returns_validated_update_and_strict_prompt`, `adapter/tests/test_validators.py::test_code_fix_rejects_direct_source_patch_paths`. |
| 4. SEED drift can generate Hermes seed-fix proposal | `test-proven` / `approval-gated` | `tests/test_llm_provider.py::test_hermes_seed_fix_posts_context_and_parses_update`, `tests/test_fix_pr.py::test_seed_fix_routes_to_seed_fix_branch_prefix`, `adapter/tests/test_validators.py::test_seed_fix_rejects_non_seed_drift_source`. |
| 5. Repos without PRD/SEED get onboarding guidance | `test-proven` | `tests/test_onboarding_orchestrator.py` and `tests/test_onboarding_pr.py`. |
| 6. 30-day adoption | `observing` | Tracking begins in `docs/operations/adoption-log.md`; this should not be claimed complete until the window is filled or the criterion is explicitly re-scoped. Future completion evidence should be a full 30-day log of relevant product PRs, check outcomes, and Slack delivery confirmations. |
| 7. L1 static PR diff vs PRD/SEED oracle + structured JSON report | `test-proven` | `tests/test_spec_parser.py`, `tests/test_spec_matcher.py`, `tests/test_drift.py`, `tests/test_guard_report.py`, `tests/test_semantic_blocking_eval.py`, and `tools/replay_pr_guard_history.py`. |

Focused evidence command used for this packet:

```bash
.venv/bin/pytest tests/test_e2e_latency.py tests/test_main_cli_gate.py tests/test_guard_report.py tests/test_comment_format.py tests/test_publish.py tests/test_llm_provider.py tests/test_fix_pr.py adapter/tests/test_service.py adapter/tests/test_validators.py tests/test_onboarding_orchestrator.py tests/test_onboarding_pr.py tests/test_workflow_public_safety.py tests/test_semantic_blocking_eval.py
```

Result: 92 passed.

## Public-safety and mutation boundaries

- The public workflow keeps fork PRs in artifact-only/no-publish mode; see
  `tests/test_workflow_public_safety.py`.
- Fix PR creation is opt-in via `PR_GUARD_MAX_FIX_PRS`; default is 0.
- The original PR branch is not directly mutated. Fixes are represented as
  separate proposal branches/PRs, with idempotent reuse behavior covered in
  `tests/test_fix_pr.py` and `tests/test_main_cli_gate.py`.
- Provider absence, timeout, malformed output, or uncertainty degrades to skip or
  no blocking drift rather than unsafe mutation; see `tests/test_llm_provider.py`
  and `adapter/tests/test_service.py`.

## Local artifact classification

- `.ouroboros/` and `.ouroboros_eval_artifact.md` are local evaluator scratch and
  are ignored by `.gitignore`.
- `completed.yaml` is a local Ouroboros skip marker. It is now ignored in
  `.gitignore` as local agent state and is not authoritative release evidence.
- `uv.lock` was generated while running `uv run`. The canonical repo install path
  is still `python -m pip install -e ".[dev,anthropic,adapter]"`, so `uv.lock` is
  locally excluded via `.git/info/exclude` rather than committed as repo policy.
  Revisit this only if the project intentionally adopts uv as the official dev
  workflow.

## Recommended next evaluate prompt

```text
Evaluate /Users/ds/GitHub/pr-guard-bot against SEED.yaml using docs/operations/evaluate-readiness-2026-05-29.md as the evidence packet. Treat AC #6 (30-day adoption) as an operational observation criterion that is tracking in docs/operations/adoption-log.md, not as a completed current-release criterion. Surface mechanical command outputs, PR #26 GitHub evidence, and any remaining unverified external evidence in the transcript.
```
