# pr-guard-bot

**PRD/SEED ↔ Pull Request consistency gate for AI-generated code.**

`pr-guard-bot` is a small GitHub Actions friendly Python tool that compares a pull request against a repository's `PRD.md`, `SEED.md`, and/or `SEED.yaml`. It helps teams using AI coding agents catch implementation/spec drift before merge, then publishes a machine-readable report, a stable PR comment, optional Slack notification, and optional fix-PR proposals.

This repository is also a dogfood target: the bot can validate its own PRs against its own PRD/SEED artifacts.

## What it does

```text
GitHub PR event
    ↓
GitHub Actions job: PR Guard
    ↓
Read PRD.md / SEED.md / SEED.yaml + PR diff
    ↓
Classify actionable drift / missing implementation / spec mismatch
    ↓
├─ Required check: fail the job when actionable drift remains
├─ pr-guard-report.json: CI artifact for machines
├─ PR comment: stable marker-based summary, updated on each run
├─ Slack notification: optional incoming webhook
└─ Optional fix PR proposal
   · code-fix proposal when implementation diverges from PRD/SEED
   · seed-fix proposal when the spec needs updating
   · Hermes webhook preferred; Anthropic API key is a legacy fallback
```

## What it intentionally does not do

- It does not directly mutate the original PR branch. Fixes are proposed as separate PRs.
- It does not interrupt coding in real time. The gate runs asynchronously at PR time.
- It does not hard-code a universal production bar. The repo's own PRD/SEED define the target.
- It is not a hosted SaaS product. It is a library/CLI/GitHub Action pattern that you can adapt.

## Repository layout

```text
pr-guard-bot/
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── PRD.md
├── SEED.md
├── SEED.yaml
├── docs/plans/
├── docs/operations/
├── pyproject.toml
├── .github/workflows/pr-guard.yml
├── src/pr_guard/
└── tests/
```

## First use in another repository

1. Add intent/spec artifacts to the target repo:

   ```bash
   ooo interview "Define this product's intent and implementation spec"
   ooo seed
   ```

2. Copy the workflow skeleton:

   ```bash
   mkdir -p .github/workflows
   cp /path/to/pr-guard-bot/.github/workflows/pr-guard.yml .github/workflows/pr-guard.yml
   ```

3. Configure optional secrets:

   - `HERMES_PR_GUARD_WEBHOOK_URL` — preferred semantic/fix provider endpoint.
   - `HERMES_PR_GUARD_WEBHOOK_TOKEN` — optional Bearer token for that endpoint.
   - `ANTHROPIC_API_KEY` — optional legacy fallback when Hermes is not configured.
   - `SLACK_WEBHOOK_URL` — optional Slack incoming webhook for PR notifications.

4. Enable branch protection and require the workflow job named **`PR Guard`** before merging.
   For the DS rollout checklist, see
   [`docs/operations/pr-guard-required-check.md`](docs/operations/pr-guard-required-check.md).

### Public repository safety defaults

The bundled workflow is safe to keep public:

- public fork PRs run with `--no-publish`, so they still produce `pr-guard-report.json` but do not receive secrets and do not publish comments, Slack messages, onboarding PRs, or fix PRs;
- same-repository PRs use `--publish-best-effort`, so a restrictive `GITHUB_TOKEN` permission setting cannot hide the JSON artifact/check result behind a comment-publishing failure;
- automatic fix-PR branch creation is disabled by default with `PR_GUARD_MAX_FIX_PRS=0`.

To opt into auto-generated fix PRs for trusted same-repository PRs, set repository variable `PR_GUARD_MAX_FIX_PRS` to a positive number and raise the workflow permission `contents` from `read` to `write`. Do not enable that mode for untrusted forks.

## CI gate mode

The core CLI can be run in GitHub Actions or locally:

```bash
python -m pr_guard \
  --repo "$REPO" \
  --pr-number "$PR_NUMBER" \
  --base-ref "$BASE_REF" \
  --head-ref "$HEAD_REF" \
  --json-output pr-guard-report.json \
  --fail-on-drift
```

Important flags:

- `--json-output`: writes a report with `schema_version`, `verdict`, `drifts`, `fix_prs`, and `suppressed`.
- `--fail-on-drift`: exits non-zero when the verdict is not `pass`, making the job usable as a required status check.
- `--no-publish`: dry-run mode; skips GitHub comments, Slack, onboarding PRs, and fix PR creation.
- `--publish-best-effort`: writes the JSON report and keeps the check verdict authoritative even when PR comment publishing is blocked by repository permissions.

PR comments use the marker `<!-- pr-guard:drift-report -->`, so repeated pushes update the existing report instead of creating comment noise.

## Hermes / LLM integration

Fix proposal generation chooses a provider in this order:

1. `HERMES_PR_GUARD_WEBHOOK_URL`: preferred. Hermes receives drift context and returns JSON shaped like:

   ```json
   {
     "action": "update",
     "new_content": "...",
     "message": "...",
     "rationale": "..."
   }
   ```

   If `HERMES_PR_GUARD_WEBHOOK_TOKEN` is present, pr-guard sends an Authorization header with a redacted Bearer token.

2. `ANTHROPIC_API_KEY`: legacy fallback for environments that do not have Hermes.
3. No provider: static drift gate, PR comment, JSON artifact, and optional Slack notification still work; LLM fix PR generation is disabled.

Ouroboros can sit behind the Hermes webhook for deeper semantic review, but the GitHub Action path intentionally keeps its deterministic baseline lightweight.

## Development

```bash
python -m pip install -e ".[dev,anthropic]"
pytest
python -m compileall -q src tests
```

Local dry-run smoke:

```bash
python -m pr_guard \
  --repo owner/repo \
  --pr-number 1 \
  --base-ref main \
  --head-ref feature-branch \
  --json-output pr-guard-report.json \
  --no-publish \
  --fail-on-drift
```

## Security notes

- Do not commit live webhook URLs, tokens, API keys, or generated logs containing credentials.
- Prefer Hermes webhook/OAuth integration over direct long-lived model-provider keys.
- Treat GitHub Actions logs and artifacts as public once the repository is public.
- Keep fork PRs in `--no-publish` mode: no secrets, no comments, no Slack, no onboarding PRs, and no fix PR branches.
- Keep automatic fix PRs opt-in for trusted same-repository PRs only.
- Keep third-party and first-party GitHub Actions pinned to immutable commit SHAs; review
  Dependabot action-update PRs as executable supply-chain changes.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and maintainer response policy.

## License

MIT — see [LICENSE](LICENSE).
