# PR Guard fixed ingress smoke

This file is a temporary same-repo smoke-test change used to verify that the
GitHub Actions PR Guard workflow can reach the fixed Hermes adapter ingress at
`https://pr-guard.daysunlabs.com/pr-guard/proposal` and publish its PR report.

Expected lifecycle:
1. Open a draft PR from this branch into `main`.
2. Wait for the `pr-guard` workflow to complete.
3. Confirm the stable `PRD/SEED Drift Report` PR comment and report artifact.
4. Close the smoke PR without merging and delete the remote smoke branch.
