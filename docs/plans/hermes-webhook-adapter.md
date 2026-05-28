# Hermes PR Guard Webhook Adapter Design

> **For Hermes:** This is the adapter plan that connects `pr-guard-bot`'s synchronous fix-provider contract to Hermes Agent safely. Implement only after the report-only PR Guard pilot has produced at least a small sample of real drift reports.

**Goal:** Let `pr-guard-bot` ask Hermes for a bounded `seed_fix` or `code_fix` proposal and receive the exact JSON shape expected by `HermesWebhookProvider`, without giving GitHub Actions direct access to a broad, stateful Hermes session.

**Architecture:** Do **not** point `HERMES_PR_GUARD_WEBHOOK_URL` directly at Hermes' generic webhook route. Hermes' documented webhook adapter is designed to accept events, turn them into agent runs, and deliver/log responses; `pr-guard-bot` needs a synchronous JSON provider response inside the CI job. Add a thin adapter service in front of a dedicated, restricted Hermes API-server/profile. The adapter owns auth, schema validation, timeouts, output repair/validation, idempotency, and repo allowlisting.

**Tech Stack:** FastAPI or small ASGI service, httpx, Pydantic, Hermes Agent API Server (`POST /v1/chat/completions`), optional Redis/SQLite idempotency cache, GitHub Actions secrets.

---

## 1. Current contracts

### `pr-guard-bot` caller contract

`src/pr_guard/llm_provider.py` already supports:

- `HERMES_PR_GUARD_WEBHOOK_URL`
- optional `HERMES_PR_GUARD_WEBHOOK_TOKEN` sent as the HTTP Authorization bearer token
- HTTP `POST` timeout: 30s
- direct JSON response or nested `{ "proposal": ... }`

Request shapes:

```jsonc
// seed_fix
{
  "task": "seed_fix",
  "drift": { "source": "seed", "source_file": "SEED.md", "line": 12, "quote": "..." },
  "seed_md_text": "# SEED\n...",
  "seed_md_path": "SEED.md",
  "proposal_shape": ["action", "new_content", "message", "rationale"]
}
```

```jsonc
// code_fix
{
  "task": "code_fix",
  "drift": { "source": "prd", "source_file": "PRD.md", "line": 34, "quote": "..." },
  "repo_context": "short file tree / context",
  "output_path": "docs/pr-guard-proposals/<slug>.md",
  "proposal_shape": ["action", "new_content", "message", "rationale"]
}
```

Accepted response shape:

```jsonc
{
  "action": "update",
  "new_content": "<full target file content>",
  "message": "docs(seed): align ...",
  "rationale": "2-3 sentence explanation"
}
```

or:

```jsonc
{ "action": "skip", "reason": "too vague / unsafe / timeout / not enough context" }
```

Important: `_maybe_generate_fix_prs()` catches provider failures and does not break the primary drift report path, but a clean `skip` response is still preferable to HTTP errors because it preserves clear CI logs.

### Hermes side contract from official docs

Hermes has two relevant primitives:

1. **Webhook platform**
   - HTTP server at `/webhooks/<route>`.
   - Validates HMAC signatures, turns payloads into agent prompts, and delivers/logs responses.
   - Good for event-driven automations and comments.
   - Not ideal as the direct `pr-guard-bot` provider because the provider expects a synchronous JSON object with `action/new_content/message/rationale`.

2. **API Server**
   - OpenAI-compatible `POST /v1/chat/completions`.
   - Stateless request/response, returns the final assistant message.
   - Better fit behind the adapter because the adapter can send a strict JSON-only prompt and validate the final content before returning it to `pr-guard-bot`.

Sources checked:

- Hermes Webhooks docs: `https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks`
- Hermes API Server docs: `https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server`

---

## 2. Recommended architecture

```text
GitHub Action / pr-guard-bot
  HERMES_PR_GUARD_WEBHOOK_URL=https://adapter.example/pr-guard/proposal
  HERMES_PR_GUARD_WEBHOOK_TOKEN=<repo/org secret>
        |
        v
PR Guard Adapter
  - Bearer auth
  - repo/task allowlist
  - payload schema validation
  - input size limits
  - timeout budget
  - idempotency cache
  - prompt construction
  - Hermes response parsing/repair
  - proposal safety validation
        |
        v
Dedicated Hermes API Server profile (`ds-pr-guard`)
  POST /v1/chat/completions on loopback, e.g. 127.0.0.1:8647
  model=ds-pr-guard
  no tools, no messaging, no durable memory
        |
        v
JSON proposal or skip
```

### Why an adapter instead of direct Hermes webhook?

Direct generic webhooks are useful for “a GitHub event happened; Hermes should comment/log/message someone.” The `pr-guard-bot` provider is narrower: “given one drift item, synchronously return a valid proposal JSON in under 30s.” The adapter should own that protocol boundary so the generic Hermes gateway does not need to become a hard real-time CI provider.

---

## 3. Adapter API

### Endpoint

`POST /pr-guard/proposal`

Headers:

```http
Authorization: Bearer <HERMES_PR_GUARD_WEBHOOK_TOKEN>
Content-Type: application/json
X-PR-Guard-Request-Id: <optional idempotency key>
```

Optional future headers from `pr-guard-bot` if we extend it:

```http
X-PR-Guard-Repo: owner/name
X-PR-Guard-PR: 123
X-PR-Guard-Commit: <head_sha>
```

### Request schema

Minimum v0 schema mirrors current `HermesWebhookProvider`; do not require a breaking `schema_version` yet.

Required common fields:

- `task`: one of `seed_fix`, `code_fix`
- `drift`: object containing at least `source`, `source_file`, `line`, `quote`, `severity`, `score`
- `proposal_shape`: must include `action`, `new_content`, `message`, `rationale`

Task-specific fields:

- `seed_fix`: `seed_md_text`, optional `seed_md_path` defaulting to `SEED.md`
- `code_fix`: `repo_context`, optional `output_path` defaulting to `docs/pr-guard-proposals/<slug>.md`

### Response schema

Adapter returns one of exactly two shapes:

```json
{
  "action": "update",
  "new_content": "...",
  "message": "docs: ...",
  "rationale": "..."
}
```

```json
{
  "action": "skip",
  "reason": "..."
}
```

HTTP status policy:

- `200` with `skip` for Hermes timeout, malformed Hermes output, low confidence, unsupported task, or insufficient context.
- `401/403` only for auth/allowlist failures.
- `413` for oversized input.
- `429` for rate limit.
- Avoid `5xx` unless the adapter itself is unhealthy; provider exceptions are noisier than explicit skips.

---

## 4. Safety policy

### Dedicated Hermes profile

Use the dedicated `ds-pr-guard` profile rather than the default operator profile. In the DS VPS pilot this profile is configured as a pure Hermes API-server proposal generator:

- profile home: `/srv/hermes/profiles/ds-pr-guard`
- API server env: `/srv/hermes/profiles/ds-pr-guard/.env`
- adapter env: `/srv/hermes/profiles/ds-pr-guard/pr-guard-adapter.env`
- API server host/port: `127.0.0.1:8647`
- model name sent by the adapter: `ds-pr-guard`

Profile policy:

- No Slack/Telegram delivery by default.
- No GitHub write tools in this synchronous provider path.
- No terminal/file mutation tools unless a later implementation explicitly requires local read-only repo context.
- No durable memory writes from raw PR payloads.
- Model should use a latency-conscious fast/default path for CI, but the output must remain bounded JSON.

### Repo allowlist

Adapter config should include explicit allowlist:

```yaml
allowed_repos:
  - Daysun-Labs/astate-brain
  - daesungkiim/pr-guard-bot
```

Because the current provider payload does not include `repo`, the first production implementation should add optional metadata to `HermesWebhookProvider._post()` before enabling this beyond a single trusted workflow. Until then, isolate by using a per-repo adapter URL/token.

### Task boundaries

`seed_fix`:

- Only allowed when `drift.source == "seed"`.
- `new_content` must be full `SEED.md` content.
- Adapter should reject outputs that delete most of the document or rewrite unrelated sections beyond a configured diff threshold.
- If uncertain whether product intent changed or code is wrong, return `skip`.

`code_fix`:

- Only allowed when `drift.source == "prd"`.
- `new_content` must be markdown for `docs/pr-guard-proposals/*.md`.
- No direct source-code patching in v0.
- Must include: missing requirement, why it matters, proposed approach, validation idea.

### Public fork safety

Do not configure `HERMES_PR_GUARD_WEBHOOK_URL` for public fork PR paths until the workflow guarantees trusted context. In current DS pilot, fork/unverified PRs already run `--no-publish`, which prevents provider calls. Keep that invariant.

---

## 5. Prompting strategy

The adapter should not send a free-form “fix this” prompt. It should send a system prompt with exact role and output schema, plus a compact user payload.

System prompt sketch:

```text
You are the Hermes-side proposal provider for pr-guard-bot.
Return JSON only. Do not use markdown fences.
You may return either:
{"action":"update","new_content":"...","message":"...","rationale":"..."}
or:
{"action":"skip","reason":"..."}

Rules:
- Prefer skip over unsafe or speculative edits.
- For seed_fix, output the full updated SEED.md and preserve unrelated text byte-for-byte.
- For code_fix, output only a markdown proposal document, not source code patches.
- Do not claim tests were run.
```

User payload sketch:

```text
Task: seed_fix|code_fix
Drift JSON:
<canonical JSON>

SEED.md or repo context:
<bounded context>

Return JSON only.
```

Set a strict adapter-side parser:

1. Strip code fences if present.
2. Parse JSON.
3. Require `action in {update, skip}`.
4. For `update`, require non-empty `new_content`, `message`, `rationale`.
5. Run task-specific validators.
6. If any step fails, return `skip` with a sanitized reason.

---

## 6. Timeout and idempotency

`pr-guard-bot` currently times out provider HTTP calls at 30s. Adapter budget:

```text
GitHub Action provider call: 30s
Adapter total budget:        25s
Hermes API call:             20s
Parse/validation:             2s
Safety margin:                3s
```

If Hermes does not return in budget, return:

```json
{ "action": "skip", "reason": "Hermes proposal timed out; leaving drift for human review." }
```

Idempotency key:

```text
sha256(repo + pr_number + head_sha + task + drift.source_file + drift.line + drift.quote)
```

Cache the final proposal/skip for at least 24h to avoid repeated model calls on CI retries.

---

## 7. Observability

Adapter should log structured events without secrets or full file bodies:

```jsonc
{
  "event": "pr_guard_adapter.proposal",
  "repo": "Daysun-Labs/astate-brain",
  "pr": 42,
  "task": "code_fix",
  "drift_source": "prd",
  "drift_line": 34,
  "status": "update|skip|rejected|timeout",
  "latency_ms": 12345,
  "idempotency_hit": false,
  "content_sha256": "..."
}
```

Metrics to track during pilot:

- provider calls per PR
- update vs skip rate
- timeout rate
- malformed output rate
- fix PRs created
- human-accepted fix PRs
- false-positive drift rate

Only after acceptance is proven should fix PR count be raised above zero in product repos.

---

## 8. GitHub Actions configuration

Recommended initial configuration for `Daysun-Labs/astate-brain` remains provider-disabled:

```yaml
env:
  PR_GUARD_MAX_FIX_PRS: "0"
```

When enabling adapter in a trusted-PR-only pilot:

```yaml
env:
  PR_GUARD_MAX_FIX_PRS: "1"
  HERMES_PR_GUARD_WEBHOOK_URL: ${{ secrets.HERMES_PR_GUARD_WEBHOOK_URL }}
  HERMES_PR_GUARD_WEBHOOK_TOKEN: ${{ secrets.HERMES_PR_GUARD_WEBHOOK_TOKEN }}
```

Keep fork/untrusted branch path on `--no-publish`, which disables provider resolution entirely.

---

## 9. Implementation plan

### Task 1: Add repo metadata to provider payload

**Objective:** Give the adapter enough context to enforce repo allowlists and idempotency.

**Files:**

- Modify: `src/pr_guard/llm_provider.py`
- Modify: `src/pr_guard/main.py`
- Test: `tests/test_llm_provider.py`

**Steps:**

1. Extend `HermesWebhookProvider` constructor with optional `repo`, `pr_number`, `head_ref`, `base_ref`.
2. Include a `metadata` object in every POST payload:

   ```json
   {
     "schema_version": "pr-guard.hermes-proposal/v1",
     "metadata": {
       "repo": "owner/name",
       "pr_number": 123,
       "base_ref": "main",
       "head_ref": "feature/x"
     }
   }
   ```

3. Keep backward compatibility: existing adapters that ignore extra fields continue to work.
4. Add tests asserting metadata is present when provided.

### Task 2: Implement adapter service

**Objective:** Provide `POST /pr-guard/proposal` with strict validation and Hermes API-server call.

**Files:**

- Create: `adapter/pr_guard_adapter/app.py`
- Create: `adapter/pr_guard_adapter/models.py`
- Create: `adapter/pr_guard_adapter/hermes_client.py`
- Create: `adapter/tests/test_app.py`
- Create: `adapter/README.md`

**Steps:**

1. Build Pydantic models for request/response.
2. Validate Bearer token with constant-time comparison.
3. Enforce repo allowlist when `metadata.repo` exists; if absent, allow only when a `SINGLE_REPO_MODE` env var is configured.
4. Enforce request body size and max text lengths.
5. Build strict JSON-only prompt by task.
6. Call Hermes API server:

   ```http
   POST http://127.0.0.1:8642/v1/chat/completions
   Authorization: Bearer <API_SERVER_KEY>
   Content-Type: application/json
   ```

7. Parse `choices[0].message.content` as JSON.
8. Return validated `update` or `skip`.

### Task 3: Add safety validators

**Objective:** Prevent the adapter from returning broad or unsafe proposals.

**Files:**

- Create: `adapter/pr_guard_adapter/validators.py`
- Test: `adapter/tests/test_validators.py`

**Validators:**

- `seed_fix` output starts with a plausible markdown heading and contains the quoted drift concept or a nearby rewritten form.
- `seed_fix` output is not empty and is within a configurable diff-size threshold versus input.
- `code_fix` output starts with a markdown heading and does not include instructions to directly push/merge.
- `message` is one-line and below 120 chars.
- `rationale` is below a configured length.

### Task 4: Add local smoke harness

**Objective:** Test the adapter without GitHub Actions.

**Files:**

- Create: `adapter/scripts/smoke.sh`
- Create: `adapter/examples/seed_fix.request.json`
- Create: `adapter/examples/code_fix.request.json`

Smoke command:

```bash
curl -sS http://127.0.0.1:8787/pr-guard/proposal \
  -H "Authorization: Bearer $HERMES_PR_GUARD_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  --data @adapter/examples/code_fix.request.json | jq .
```

Expected: `action` is `update` or `skip`; never plain prose.

### Task 5: Pilot behind fix count = 1

**Objective:** Run on one trusted DS repo with controlled side effects.

**Scope:** `Daysun-Labs/astate-brain` only.

**Steps:**

1. Keep Required Check already in place.
2. Add adapter secrets to repo/org only after adapter smoke passes.
3. Set `PR_GUARD_MAX_FIX_PRS=1` only for trusted PRs.
4. Observe at least 5 real PR Guard runs before raising scope.
5. Do not enable public fork provider calls.

---

## 10. Rollout decision gates

### Gate A: Adapter local smoke

Pass criteria:

- Auth rejects missing/wrong token.
- Valid sample returns JSON only.
- Hermes timeout becomes `skip`, not a 500.
- Malformed model output becomes `skip`.

### Gate B: Single-repo pilot

Pass criteria:

- No provider call on fork/untrusted PR path.
- At least 5 PR Guard runs with no CI instability caused by adapter.
- `skip` reasons are understandable in logs.
- Any generated fix PR is draft and reviewable.

### Gate C: DS-wide reusable workflow consideration

Pass criteria:

- False-positive drift rate acceptable.
- Human-accepted fix proposal rate justifies added complexity.
- Packaging path is portable: pinned SHA, composite action, or reusable workflow.

---

## 11. Open decisions

1. **Adapter home:** put the adapter in this repo under `adapter/`, or in a DS infra repo?
   - Recommendation: start in this repo while the protocol evolves; move to DS infra only when multiple repos consume it.

2. **Hermes profile:** reuse `ds-default` API server or create dedicated `ds-pr-guard`?
   - Recommendation: dedicated `ds-pr-guard` profile for blast-radius control.

3. **Fix PR behavior:** enable `seed_fix`, `code_fix`, or both first?
   - Recommendation: enable `code_fix` proposal docs first. Keep `seed_fix` disabled until the team is comfortable with bot-authored spec edits.

4. **Durable learning:** should every drift report go to gbrain?
   - Recommendation: not from the synchronous adapter. Add a separate async report ingestion path after the provider path is stable.

---

## Recommendation

Build the adapter, but keep it out of the current enforced gate until one more step is done: add repo metadata to `HermesWebhookProvider` and implement local adapter smoke tests. The first production mode should be:

```text
repo: Daysun-Labs/astate-brain
trusted PRs only
PR_GUARD_MAX_FIX_PRS=1
code_fix only
output: draft docs proposal PR
no seed rewrites
no public fork provider calls
```

This preserves the useful part — Hermes can turn drift into concrete review material — without letting a synchronous CI hook become an unbounded agent writer.
