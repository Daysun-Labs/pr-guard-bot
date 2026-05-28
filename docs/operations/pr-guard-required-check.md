# PR Guard required-check operations

This runbook describes the DS operating posture for using `pr-guard-bot` as a
PRD/SEED drift gate in GitHub Actions.

## Current DS ingress

- Public adapter URL: `https://pr-guard.daysunlabs.com/pr-guard/proposal`
- Adapter origin: `http://127.0.0.1:8788`
- Hermes API origin behind the adapter: `http://127.0.0.1:8647`
- Runtime profile: dedicated `ds-pr-guard`; do not point PR payloads at
  `ds-default` or `ds-eng`.
- Public health check: `https://pr-guard.daysunlabs.com/healthz`

Required repository secrets for repos that enable the Hermes proposal provider:

- `HERMES_PR_GUARD_WEBHOOK_URL`
- `HERMES_PR_GUARD_WEBHOOK_TOKEN`

Default repository variable posture:

- `PR_GUARD_MAX_FIX_PRS=0`

Keep automatic fix PR creation disabled unless a trusted same-repository rollout
is separately reviewed and approved.

## Workflow supply-chain policy

The bundled workflow pins GitHub Actions to immutable commit SHAs rather than
mutable major-version tags:

| Action | Human version | Pinned SHA |
| --- | --- | --- |
| `actions/checkout` | `v4` | `34e114876b0b11c390a56381ad16ebd13914f8d5` |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| `actions/upload-artifact` | `v4` | `ea165f8d65b6e75b540449e92b4886f43607fa02` |

Dependabot is enabled for `github-actions` updates. Review those PRs as normal
code changes because a SHA bump changes the executable CI supply chain.

## Recommended rollout stages

1. **Artifact-only pilot**
   - Run PR Guard without publishing comments or fix proposals.
   - Confirm `pr-guard-report.json` shape and false-positive rate.
2. **Comment/report mode**
   - Enable `pull-requests: write` / `issues: write` and stable PR comments.
   - Keep `PR_GUARD_MAX_FIX_PRS=0`.
3. **Required check**
   - After several representative PRs have produced acceptable signal, configure
     branch protection to require the `PR Guard` check on `main`.
   - Verify the exact required-check context from a green PR before enforcing it;
     the current workflow job name is `PR Guard`.
4. **Optional proposal provider**
   - Set `HERMES_PR_GUARD_WEBHOOK_URL` and `HERMES_PR_GUARD_WEBHOOK_TOKEN`.
   - Keep the provider behind the dedicated `ds-pr-guard` profile and adapter.
5. **Optional fix PRs**
   - Only enable for trusted same-repo PRs after a separate approval.
   - Requires `contents: write` and a positive `PR_GUARD_MAX_FIX_PRS` value.

## Branch protection checklist

Before enabling required status checks on a target repository:

- [ ] `PRD.md` and/or `SEED.md` exists and is current enough to gate against.
- [ ] The workflow has run on at least one same-repo PR and produced a stable
      `PRD/SEED Drift Report` comment or artifact.
- [ ] Fork PR behavior remains artifact-only / no secrets / no write side effects.
- [ ] `PR Guard` is visible as a successful check on a recent PR.
- [ ] `PR_GUARD_MAX_FIX_PRS` is unset or `0`.
- [ ] `HERMES_PR_GUARD_WEBHOOK_TOKEN` has not been printed in logs or artifacts.

Example branch protection intent for `main`:

```text
Require status checks before merging: enabled
Required checks: PR Guard
Require branches to be up to date before merging: repo-owner decision
Restrict who can push: repo-owner decision
Include administrators: repo-owner decision
```

Do not change branch protection, repository secrets, or DNS/Cloudflare settings
without an explicit DS approval for that specific repository.

## Rollback

- Required check issue: remove `PR Guard` from the required status-check list.
- Webhook/provider issue: remove or rotate `HERMES_PR_GUARD_WEBHOOK_URL` and
  `HERMES_PR_GUARD_WEBHOOK_TOKEN` in the target repository.
- Ingress issue: stop or disable `cloudflared-pr-guard.service`, or remove the
  `pr-guard.daysunlabs.com` DNS route after approval.
- Workflow regression: revert the workflow commit or close the adoption PR.
