# Contributing

Thanks for helping harden `pr-guard-bot`. This repository is public so other AI-coding/Hermes workflows can pin and reuse it, but it is still dogfood-stage infrastructure rather than a marketed SaaS product.

## Development setup

```bash
python -m pip install -e ".[dev,anthropic]"
pytest
python -m compileall -q src tests
```

Use Python 3.12+.

## Pull request expectations

Before opening a PR:

1. Keep the change small and tied to `PRD.md` / `SEED.md`.
2. Add or update tests for behavior changes.
3. Run `pytest` and `python -m compileall -q src tests`.
4. Do not include live secrets, private repository content, raw GitHub Actions logs with credentials, or real webhook URLs.
5. If the change modifies the workflow/security model, update `README.md`, `SEED.md`, and `SECURITY.md` where relevant.

## Public fork PR behavior

Fork PRs intentionally run in `--no-publish` mode. That means the guard can still produce `pr-guard-report.json` and a check verdict, but it will not receive secrets and will not publish PR comments, Slack notifications, onboarding PRs, or fix PR branches.

If your fork PR needs to demonstrate publish/fix-PR behavior, include a redacted local transcript or test instead of expecting CI to use repository secrets.

## Fix PR generation policy

Automatic fix PR creation is opt-in for trusted same-repository PRs only:

- repository variable `PR_GUARD_MAX_FIX_PRS` must be positive;
- workflow `permissions.contents` must be raised to `write`;
- Hermes webhook is preferred over direct provider keys.

Do not enable fix PR generation for untrusted forks.

## Security issues

Follow `SECURITY.md`. Do not disclose exploit details or credentials in public issues or PRs.
