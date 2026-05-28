from __future__ import annotations

import json
import os
from hmac import compare_digest
from typing import Mapping

from .core import AdapterConfig, ForbiddenRequest, InMemoryIdempotencyCache, ProposalService


def _float_from_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def config_from_env(env: Mapping[str, str] | None = None) -> AdapterConfig:
    env = env or os.environ
    allowed_repos = {
        item.strip()
        for item in (env.get("PR_GUARD_ALLOWED_REPOS") or "").split(",")
        if item.strip()
    }
    return AdapterConfig(
        allowed_repos=allowed_repos,
        single_repo_mode=(env.get("PR_GUARD_SINGLE_REPO_MODE") or "").strip() or None,
        hermes_api_url=(env.get("HERMES_API_URL") or "http://127.0.0.1:8642").strip(),
        hermes_api_key=(env.get("HERMES_API_KEY") or "").strip() or None,
        model=(env.get("HERMES_PR_GUARD_MODEL") or "hermes-agent").strip(),
        hermes_timeout=_float_from_env(env, "HERMES_TIMEOUT_SECONDS", AdapterConfig.hermes_timeout),
        adapter_token=(env.get("PR_GUARD_ADAPTER_TOKEN") or "").strip() or None,
    )


def verify_bearer_token(header_value: str | None, expected_token: str | None) -> bool:
    if not expected_token:
        return False
    if not header_value or not header_value.startswith("Bearer "):
        return False
    token = header_value.removeprefix("Bearer ").strip()
    return compare_digest(token, expected_token)


def create_app(
    *,
    config: AdapterConfig | None = None,
    service: ProposalService | None = None,
):
    """Create the optional FastAPI app.

    FastAPI is an adapter extra, not a base pr-guard dependency. Import lazily so
    unit tests and CLI users do not need the web server stack installed.
    """

    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("Install adapter dependencies: pip install -e '.[adapter]'") from exc

    cfg = config or config_from_env()
    svc = service or ProposalService(cfg, cache=InMemoryIdempotencyCache())
    app = FastAPI(title="PR Guard Hermes Adapter", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/pr-guard/proposal")
    async def proposal(request: Request):
        if not verify_bearer_token(request.headers.get("authorization"), cfg.adapter_token):
            raise HTTPException(status_code=401, detail="missing or invalid bearer token")

        body = await request.body()
        if len(body) > cfg.max_body_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JSONResponse({"action": "skip", "reason": "Malformed JSON request."})

        try:
            result = svc.handle(payload, request_id=request.headers.get("x-pr-guard-request-id"))
        except ForbiddenRequest as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return JSONResponse(result)

    return app


if __name__ == "__main__":  # pragma: no cover - convenience entrypoint
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("Install adapter dependencies: pip install -e '.[adapter]'") from exc

    uvicorn.run(create_app(), host="127.0.0.1", port=8787)
