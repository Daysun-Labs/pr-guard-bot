# Hermes PR Guard Adapter

Small synchronous adapter for `HERMES_PR_GUARD_WEBHOOK_URL`.

`pr-guard-bot` runs inside GitHub Actions and expects one JSON proposal response
within its provider timeout. Hermes' generic webhook platform is event-oriented,
so this adapter sits between PR Guard and a Hermes API Server:

```text
pr-guard-bot -> POST /pr-guard/proposal -> Hermes API Server /v1/chat/completions
```

## Why not use `ds-default` directly?

A dedicated Hermes profile is recommended for production because PR payloads are
untrusted review material and this path is synchronous CI infrastructure. The
profile should have no messaging delivery, no GitHub write tools, and no durable
memory writes. `ds-default` or `ds-eng` can be used for local/dev smoke tests, but
not as the default production blast radius.

## Install

```bash
pip install -e '.[adapter]'
```

## Environment

Production should run against the dedicated `ds-pr-guard` Hermes profile rather
than a broad operator profile. The profile owns two local secret files outside
this repository:

```text
/srv/hermes/profiles/ds-pr-guard/.env                  # Hermes API Server env
/srv/hermes/profiles/ds-pr-guard/pr-guard-adapter.env  # Adapter env
```

The adapter env should contain at least:

```bash
export PR_GUARD_ADAPTER_TOKEN='shared-secret-from-github-actions'
export PR_GUARD_ALLOWED_REPOS='Daysun-Labs/astate-brain'
export HERMES_API_URL='http://127.0.0.1:8647'
export HERMES_API_KEY='api-server-key-from-ds-pr-guard-env'
export HERMES_PR_GUARD_MODEL='ds-pr-guard'
export HERMES_TIMEOUT_SECONDS='20'
```

If old PR Guard clients do not yet send `metadata.repo`, set exactly one repo:

```bash
export PR_GUARD_SINGLE_REPO_MODE='Daysun-Labs/astate-brain'
```

## Run locally

```bash
PYTHONPATH=adapter python -m pr_guard_adapter.app
```

or with uvicorn:

```bash
PYTHONPATH=adapter uvicorn pr_guard_adapter.app:create_app --factory --host 127.0.0.1 --port 8787
```

## Smoke

```bash
adapter/scripts/smoke.sh adapter/examples/code_fix.request.json
```

Expected output is always one of:

```json
{"action":"update","new_content":"...","message":"...","rationale":"..."}
```

or:

```json
{"action":"skip","reason":"..."}
```
