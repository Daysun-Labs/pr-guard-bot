# PR Guard — Drift False-Positive Remediation (Handoff)

- **Date:** 2026-05-29
- **Branch:** `claude/youthful-leakey-532f58` (3 commits ahead of `main`)
- **Status:** #1–#3 shipped. Semantic blocking and #5 cleanups remain.

## TL;DR

The PR-guard CI gate was failing frequently on **false positives** rather than
meaningful drift. Investigation traced this to a static matcher whose entire
fail surface collapsed to a single degenerate value, amplified by substring
matching and prose-vocabulary overlap. Three deterministic fixes landed:

1. **#1** — static drift is now *advisory* (non-blocking); the verdict fails
   only on a separate *blocking* set.
2. **#2** — subword token-set matching (no substring collisions) + evidence
   from added lines only (deletions don't count).
3. **#3** — token-coverage evidence is scoped to **code changes** only;
   doc/config-only PRs no longer manufacture drift.

Replaying this repo's own last 12 commits: **default-mode false-positive CI
failures went 5 → 0**, and every chore/docs-only PR is now clean in all modes.

## Background

The guard (`src/pr_guard/`) parses PRD.md/SEED.md/SEED.yaml into requirements,
diffs the PR, and reports requirements the diff fails to "address." Run in CI
via `.github/workflows/pr-guard.yml` with `--fail-on-drift`, it was a required
check. The matcher is intentionally static/syntactic (token overlap); deeper
semantic review was always meant to be an LLM/Hermes oracle layered on top.

## Root causes found

| ID | Issue | Status |
|----|-------|--------|
| **F1** | Actionable-drift band `[floor=0.33, threshold=0.34)` is reachable only by token-coverage = **1/3 (0.3333)**. The whole FAIL surface was "exactly 1/3 of a requirement's tokens appear in the diff." 5/12 real commits failed, every one at 0.3333. | Mitigated by #1 (advisory non-blocking); fully resolved only with semantic blocking. |
| **F2** | Substring matching (`tok in haystack`) — "pr" matched "print", "ci" matched "specific". | Fixed (#2) |
| **F5** | Removed diff lines counted as evidence — deleting `def foo` "satisfied" a requirement naming `foo`. | Fixed (#2) |
| **F3** | Drift computed against the whole spec with no PR scope; doc/config PRs matched behaviour requirements via shared prose vocabulary. | Fixed deterministically (#3); residual semantic judgement deferred. |
| **F6** | `drift_classifier.py` is dead code — only its own test imports it. | **TODO (#5)** |
| **F7** | `workflow_dispatch` smoke test (`pytest -v`) errors at collection: CI installs `.[dev,anthropic]` but `adapter/tests` + `tests/test_adapter_validators.py` need `pydantic`/`fastapi` (the `adapter` extra). PR-event path is unaffected. | **TODO (#5)** |

## Work completed

### #1 — advisory vs blocking split (`928acb1`)
- `drift.select_blocking_drift(advisory, *, fail_on_advisory=False)` — the seam
  that decides what fails CI. Static layer returns `[]` (nothing blocks);
  `--fail-on-advisory-drift` opts into legacy strict (all advisory blocks).
- `guard_report.determine_verdict(*, blocking_count, fix_pr_count)` — fix PR →
  `needs_fix_review`; blocking > 0 → `fail`; else `pass`. Report gains
  `blocking_count`; `drift_count` stays the advisory/displayed count.
- `main.py` wires advisory → comment/JSON, blocking → verdict; adds
  `--fail-on-advisory-drift`.

### #2 — subword matching + added-only evidence (`d08f4ca`)
- `spec_matcher`: `_SUBTOKEN_RE` splits identifiers (`send_slack_webhook` →
  {send, slack, webhook}); matching is exact set membership, not substring.
- `diff_extractor`: `NormalizedDiff.added_text` / `added_symbols` (added lines /
  touched symbols only). `changed_text` / `all_symbols` kept for back-compat.

### #3 — scope token evidence to code (`c5015d7`)
- `spec_matcher._is_code_path` + haystack built from **code-file** added text,
  symbols, and code-path components only. Documenting/configuring a requirement
  is not evidence of implementing it. Explicit file/symbol references are still
  honoured for any touched file.

## Current behaviour contract

- **Default:** static drift is advisory — surfaced in the PR comment and
  `pr-guard-report.json`, but **never fails the check**. Verdict is `pass`
  unless a fix PR was generated (`needs_fix_review`).
- **`--fail-on-advisory-drift`:** legacy strict — every advisory item blocks.
- **Blocking drift:** currently only produced by the (opt-in) strict path; the
  `select_blocking_drift` seam is where a future semantic oracle plugs in.
- Report keys: `verdict`, `drift_count` (advisory), `blocking_count`,
  `fix_pr_count`, `drifts`, `fix_prs`, `suppressed`.

## Evidence (12-commit self-replay)

| Metric | Original | #1 | #2 | #3 |
|--------|----------|----|----|----|
| Default-mode FP failures | 5 | 0 | 0 | 0 |
| Strict-mode failures | 5 | 6 | 9 | **5 (all code PRs)** |
| Total advisory items | ~9 (inflated) | 9 | 19 | 15 |
| chore/docs-only PRs flagged | all | some | some | **none** |

## Verify

```bash
python -m pip install -e ".[dev,anthropic]"
PYTHONPATH=src pytest tests/ -q          # 212 passing
# Self-replay: run the guard against the repo's own diff
PYTHONPATH=src python -m pr_guard --repo owner/repo --pr-number 0 \
  --base-ref main --head-ref HEAD --json-output /tmp/r.json \
  --no-publish --fail-on-drift           # exit 0, advisory=0
```

## Remaining work

### A. Semantic blocking signal (the real #3 tail)
A trustworthy *static* blocking signal isn't achievable — "PR touches the file a
requirement names but doesn't satisfy it" can't be distinguished from "touched
that file for an unrelated reason" without understanding intent. Populate
`select_blocking_drift` from the existing LLM provider abstraction
(`llm_provider.py` / `resolve_llm_provider`, already used for fix-PR
generation): classify scoped advisory items as genuine drift vs noise, and only
those become blocking. Keep it degrade-gracefully (no key → no blocking → CI
green, as today).

### B. #5 cleanups
- **F6:** wire `drift_classifier` into the comment (it produces
  spec-missing/violation/ambiguous categories) **or** delete it. Right now it's
  dead code with tests that don't reflect production.
- **F7:** make `pytest -v` (the `workflow_dispatch` smoke job) install the
  `adapter` extra, **or** scope pytest `testpaths` so the smoke job doesn't
  collect adapter tests it can't import.

## Next-session prompt

> Continue the PR-guard drift false-positive remediation on branch
> `claude/youthful-leakey-532f58`. Read `docs/plans/drift-false-positive-remediation.md`
> and the project memory `pr-guard-qa-remediation`. #1–#3 are done. Do the #5
> cleanups first (they're low-risk): (F6) wire `drift_classifier` into the PR
> comment or delete it, and (F7) fix the `workflow_dispatch` smoke-test
> dependency gap by adding the `adapter` extra to the CI install or scoping
> pytest `testpaths`. Then scope out the semantic blocking signal: design how
> `select_blocking_drift` would consume the existing `llm_provider` abstraction
> to classify scoped advisory drift into genuine blocking drift, degrading to
> CI-green when no provider key is present. Verify with `PYTHONPATH=src pytest
> tests/ -q` and the 12-commit self-replay before committing each step.
