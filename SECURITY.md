# Security Policy

`pr-guard-bot` is a public GitHub Actions/CLI tool that may run in repositories containing private product plans, PR diffs, and optional webhook/model-provider secrets. Treat integrations as security-sensitive even though the static gate itself is small.

## Supported versions

The project is pre-1.0. Security fixes are applied to `main` first. Downstream repositories should pin either a reviewed commit SHA or an explicit release tag.

## Reporting a vulnerability

Please do **not** open a public issue with exploit details, live webhook URLs, tokens, logs containing credentials, or private repository content.

Preferred reporting path:

1. Use GitHub private vulnerability reporting if it is enabled for this repository.
2. If private reporting is unavailable, contact the maintainer through the GitHub profile and share only a minimal, redacted summary until a private channel is established.

A useful report includes:

- affected commit/tag;
- whether the issue requires `pull_request`, fork PRs, repository secrets, or a configured Hermes/Anthropic/Slack provider;
- a redacted proof of concept;
- expected impact and any known workaround.

## Maintainer response target

- Acknowledge: best effort within 7 days.
- Triage: classify severity and affected configurations.
- Fix: patch `main`, add regression tests, and recommend whether downstream users must rotate secrets or update pinned SHAs.

## Public-fork safety model

The bundled workflow keeps public fork PRs in artifact-only mode:

- no repository secrets are exposed;
- no PR comments or Slack notifications are published;
- no onboarding PRs or fix PR branches are created;
- the check verdict and `pr-guard-report.json` artifact remain available.

Automatic fix PRs require trusted same-repository execution, an explicit positive `PR_GUARD_MAX_FIX_PRS` value, and `contents: write` workflow permission. Do not enable that mode for untrusted forks.

## Secret handling rules

- Never commit live `SLACK_WEBHOOK_URL`, `HERMES_PR_GUARD_WEBHOOK_TOKEN`, `ANTHROPIC_API_KEY`, GitHub PATs, or generated logs containing those values.
- Prefer Hermes webhook/OAuth integration over direct long-lived model-provider keys.
- Treat GitHub Actions logs and artifacts as public when the repository is public.
- Redact tokens in bug reports, screenshots, test fixtures, and PR comments.
