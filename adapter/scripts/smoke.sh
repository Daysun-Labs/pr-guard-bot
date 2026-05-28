#!/usr/bin/env bash
set -euo pipefail

payload="${1:-adapter/examples/code_fix.request.json}"
url="${PR_GUARD_ADAPTER_URL:-http://127.0.0.1:8787/pr-guard/proposal}"
token="${PR_GUARD_ADAPTER_TOKEN:?set PR_GUARD_ADAPTER_TOKEN}"
auth_scheme="Bearer"

json_python="${PYTHON:-python3}"

curl -sS "$url" \
  -H "Authorization: ${auth_scheme} ${token}" \
  -H "Content-Type: application/json" \
  -H "X-PR-Guard-Request-Id: smoke-$(basename "$payload")" \
  --data @"$payload" | "$json_python" -m json.tool
