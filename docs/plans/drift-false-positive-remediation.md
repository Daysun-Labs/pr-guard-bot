# PR Guard - Drift False-Positive Remediation (Handoff)

- **Date:** 2026-05-29
- **Branch:** `claude/youthful-leakey-532f58`
- **Status:** #1-#3, #5 cleanup, repo-side semantic blocking, reason
  provenance, and semantic eval fixtures are shipped. Remaining work is
  Hermes-side handler rollout plus live Actions smoke.

## TL;DR

The PR-guard CI gate was failing on false positives rather than meaningful
drift. Investigation traced this to a static matcher whose fail surface
collapsed to one degenerate value: token coverage of exactly 1/3, amplified by
substring matching and prose-vocabulary overlap.

Repo-side remediation now does five things:

1. **#1** - static drift is advisory by default; the verdict fails only on a
   separate blocking set.
2. **#2** - subword token-set matching removes substring collisions and added
   lines/symbols are the only implementation evidence.
3. **#3** - token-coverage evidence is scoped to code changes, so docs/config
   PRs do not manufacture implementation drift.
4. **#5** - `drift_classifier` is wired into PR comments and workflow-dispatch
   smoke installs the `adapter` extra.
5. **Semantic blocking** - existing LLM providers can promote scoped advisory
   drift to blocking drift, with reason provenance in the JSON report and PR
   comment. No provider key or provider failure still degrades to CI green.

Replaying this repo's own last 12 commits: default-mode false-positive CI
failures remain 0, and every chore/docs-only PR remains clean in all modes.

## Root Causes

| ID | Issue | Status |
|----|-------|--------|
| **F1** | Actionable-drift band `[floor=0.33, threshold=0.34)` is reachable only by token-coverage = 1/3. The whole FAIL surface was "exactly 1/3 of a requirement's tokens appear in the diff." | Mitigated by advisory-by-default; repo-side semantic blocking seam added. Real blocking now requires provider evidence. |
| **F2** | Substring matching (`tok in haystack`) let `pr` match `print` and `ci` match `specific`. | Fixed (#2). |
| **F5** | Removed diff lines counted as evidence; deleting code could "satisfy" a requirement. | Fixed (#2). |
| **F3** | Drift was computed against the whole spec with no PR scope; doc/config PRs matched behavior requirements via shared prose vocabulary. | Fixed deterministically (#3); residual judgment is semantic. |
| **F6** | `drift_classifier.py` was dead code. | Fixed (#5): PR comments show classifier categories. |
| **F7** | `workflow_dispatch` smoke installed `.[dev,anthropic]` but collected adapter tests needing FastAPI/Pydantic. | Fixed (#5): CI installs `.[dev,anthropic,adapter]`. |

## Work Completed

### #1 - Advisory vs Blocking Split (`0ae5280`)

- `drift.select_blocking_drift(advisory, *, fail_on_advisory=False)` became the
  backwards-compatible seam that decides what fails CI.
- Static token-coverage drift is advisory by default.
- `--fail-on-advisory-drift` preserves legacy strict behavior.
- `guard_report` gained `blocking_count`; `drift_count` remains advisory count.

### #2 - Exact Matching and Added-Only Evidence (`4a3f648`)

- `spec_matcher` splits identifiers into exact subtokens, so
  `send_slack_webhook` still matches `webhook`, while substring collisions are
  gone.
- `diff_extractor` added `NormalizedDiff.added_text` and `added_symbols`; removed
  lines no longer count as implementation evidence.

### #3 - Scope Token Evidence to Code (`2158675`)

- Token-coverage haystack is built from code-file added text, symbols, and code
  path components.
- Documenting/configuring a requirement is not evidence of implementing it.
- Explicit file/symbol references are still honored for any touched file.

### #5 - Cleanup and Workflow Smoke Deps (`2a3b16f`)

- `comment_format` imports `drift_classifier.classify_drift` and surfaces
  `spec-missing`, `spec-violation`, `spec-ambiguous`, or `unknown` in both the
  comment summary and each drift row.
- `.github/workflows/pr-guard.yml` installs `.[dev,anthropic,adapter]`, so
  workflow-dispatch `pytest -v` can collect adapter tests that need FastAPI and
  Pydantic.

### Semantic Blocking Provider Seam (`fa28aaf` + follow-up reason work)

- `select_blocking_drift_decisions` wraps blocking findings with
  `BlockingDriftDecision` reason/source provenance; `select_blocking_drift`
  remains the backwards-compatible drift-only wrapper.
- `LLMProvider` now includes `classify_blocking_drift(advisory, diff_summary)`.
- Hermes receives `task: blocking_drift_classification` with
  `schema_version: pr-guard.blocking-drift/v1`; Anthropic fallback uses the same
  conservative JSON decision shape.
- `main.py` builds a compact added-line diff summary for the classifier, writes
  semantic blocking reasons into PR comments, and records them in
  `pr-guard-report.json`.
- Provider absence, missing classifier method, malformed responses, and provider
  exceptions all degrade to zero blocking drift.

## Current Behavior Contract

- **Default:** static drift is advisory. It appears in the PR comment and
  `pr-guard-report.json`, but does not fail the check unless a semantic provider
  explicitly promotes an item to blocking.
- **No provider key:** no semantic classification is attempted; advisory drift
  remains non-blocking and CI stays green.
- **Provider failure or uncertainty:** no blocking drift.
- **`--fail-on-advisory-drift`:** legacy strict mode; every advisory item blocks.
- **Report keys:** `verdict`, `drift_count`, `blocking_count`, `fix_pr_count`,
  `drifts`, `blocking_drifts`, `fix_prs`, `suppressed`, `summary`.

## Evidence

| Metric | Original | #1 | #2 | #3 | Current repo-side |
|--------|----------|----|----|----|-------------------|
| Default-mode FP failures | 5 | 0 | 0 | 0 | 0 |
| Strict-mode failures | 5 | 6 | 9 | 5 | 6 |
| Total advisory items | ~9 | 9 | 19 | 15 | 15 |
| Chore/docs-only PRs flagged | all | some | some | none | none |

Semantic eval fixtures now cover:

- docs/config noise stays green;
- scoped code violation blocks when a provider returns a blocking decision;
- provider exception degrades to green;
- blocking reasons are preserved in report/comment surfaces.

## Verify

```bash
python -m pip install -e ".[dev,anthropic,adapter]"
PYTHONPATH=src pytest tests/ -q
PYTHONPATH=src pytest -v

# Self-replay: run guard primitives over the repo's own recent commits.
# Provider-less default mode must keep default_failures=0.
PYTHONPATH=src python - <<'PY'
from pathlib import Path
import subprocess
from pr_guard.diff_extractor import parse_unified_diff
from pr_guard.drift import detect_drift, filter_actionable_drift, select_blocking_drift
from pr_guard.spec_parser import parse_repo

spec = parse_repo(Path("."))
commits = subprocess.check_output(
    ["git", "rev-list", "--max-count=12", "HEAD"], text=True
).splitlines()
default_failures = strict_failures = advisory_total = 0
for commit in reversed(commits):
    parents = subprocess.check_output(
        ["git", "rev-list", "--parents", "-n", "1", commit], text=True
    ).split()
    if len(parents) < 2:
        continue
    diff = parse_unified_diff(
        subprocess.check_output(["git", "diff", f"{parents[1]}...{commit}"], text=True)
    )
    raw = detect_drift(spec, diff)
    advisory, _ = filter_actionable_drift(raw)
    default_failures += 1 if select_blocking_drift(advisory, provider=None) else 0
    strict_failures += 1 if select_blocking_drift(advisory, fail_on_advisory=True) else 0
    advisory_total += len(advisory)
print(
    f"default_failures={default_failures} "
    f"strict_failures={strict_failures} advisory_total={advisory_total}"
)
if default_failures:
    raise SystemExit(1)
PY
```

## Remaining Work

### A. Hermes-Side Semantic Handler

Implement the `blocking_drift_classification` task in the Hermes webhook target.
It should read `advisory_drifts` and `diff_summary`, apply the conservative
blocking policy, and return:

```json
{"blocking": [{"index": 0, "reason": "short evidence-based reason"}]}
```

Return `{"blocking": []}` for uncertainty, docs/config noise, generic
vocabulary overlap, malformed context, or insufficient evidence.

### B. Live Workflow-Dispatch Smoke

After pushing this branch, run the GitHub Actions `workflow_dispatch` path once
to confirm `pytest -v` collects adapter tests with `.[dev,anthropic,adapter]` in
the hosted runner.

### C. Expand Semantic Eval Coverage

Add more gold cases as real PR examples appear: intentional spec updates,
renames, touched-but-unrelated code, and true missing-requirement code changes.

## Next-Session Prompt

> Continue the PR-guard drift false-positive remediation on branch
> `claude/youthful-leakey-532f58`. Repo-side #1-#3, #5 cleanup, semantic
> blocking provider seam, blocking reason provenance, and semantic eval fixtures
> are done. Next, implement the Hermes webhook handler for
> `blocking_drift_classification` and run the live workflow-dispatch smoke after
> pushing the branch. Keep the conservative policy: no provider/uncertainty -> no
> blocking -> CI green. Verify with `PYTHONPATH=src pytest tests/ -q`,
> `PYTHONPATH=src pytest -v`, and the 12-commit self-replay.
