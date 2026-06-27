from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import ValidationError

from .models import BlockingDriftRequest, Metadata, ProposalRequest, ReviewRequest
from .validators import (
    parse_model_proposal,
    skip,
    validate_blocking_decision,
    validate_proposal,
)

JsonObject = dict[str, object]

SYSTEM_PROMPT = """You are the Hermes-side proposal provider for pr-guard-bot.
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
"""

BLOCKING_SYSTEM_PROMPT = """You are pr-guard's Hermes-side semantic blocking classifier.
Return JSON only. Do not use markdown fences.
You may return either:
{"blocking":[{"index":0,"reason":"short evidence-based reason"}]}
or:
{"blocking":[]}

Rules:
- Only mark an item blocking when the diff is clearly scoped to that requirement
  and the requirement is still genuinely missing or contradicted.
- Do not block on docs/config-only changes, generic vocabulary overlap,
  ambiguous requirements, malformed context, or insufficient evidence.
- Prefer {"blocking":[]} whenever uncertain.
- Do not claim tests were run.
"""

REVIEW_SYSTEM_PROMPT = (
    "You are pr-guard Hermes-side general code reviewer. Return JSON only. Do not use "
    "markdown fences. Review PR diff for bug/security/trust_boundary/perf/quality issues; "
    "exclude PRD/SEED drift; be conservative. Output exactly: "
    '{"score": <0-5 int>, "summary": "<short>", "findings": '
    '[{"category":"bug|security|trust_boundary|perf|quality","severity":"error|warn|info",'
    '"file":"<path>","line":<int>,"quote":"<short>","suggestion":"<short>"}]}. '
    "Do not claim tests were run."
)


class ForbiddenRequest(Exception):
    """Raised when the adapter rejects an authenticated but disallowed request."""


class HermesClient(Protocol):
    def complete_json(self, messages: list[dict[str, str]]) -> str: ...


class IdempotencyCache(Protocol):
    def get(self, key: str) -> JsonObject | None: ...

    def set(self, key: str, value: JsonObject) -> None: ...


@dataclass(frozen=True)
class AdapterConfig:
    """Runtime configuration for the Hermes PR Guard adapter."""

    allowed_repos: set[str] = field(default_factory=set)
    single_repo_mode: str | None = None
    hermes_api_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str | None = None
    model: str = "hermes-agent"
    hermes_timeout: float = 20.0
    adapter_token: str | None = None
    max_body_bytes: int = 256_000
    max_seed_chars: int = 120_000
    max_repo_context_chars: int = 40_000
    max_diff_summary_chars: int = 40_000


class InMemoryIdempotencyCache:
    """Tiny process-local cache for CI retries and local smoke tests."""

    def __init__(self) -> None:
        self._items: dict[str, JsonObject] = {}

    def get(self, key: str) -> JsonObject | None:
        value = self._items.get(key)
        return dict(value) if value is not None else None

    def set(self, key: str, value: JsonObject) -> None:
        self._items[key] = dict(value)


class HermesAPIClient:
    """Minimal OpenAI-compatible client for Hermes API Server."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str | None,
        model: str,
        timeout: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.http_client = http_client or httpx.Client()

    def complete_json(self, messages: list[dict[str, str]]) -> str:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = self.http_client.post(
            f"{self.api_url}/v1/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "stream": False,
            },
            headers=headers or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("Hermes API response content was not a string")
        return content


class ProposalService:
    """Synchronous PR Guard proposal service backed by Hermes."""

    def __init__(
        self,
        config: AdapterConfig,
        *,
        hermes_client: HermesClient | None = None,
        cache: IdempotencyCache | None = None,
    ) -> None:
        self.config = config
        self.hermes_client = hermes_client or HermesAPIClient(
            api_url=config.hermes_api_url,
            api_key=config.hermes_api_key,
            model=config.model,
            timeout=config.hermes_timeout,
        )
        self.cache = cache

    def handle(self, payload: object, *, request_id: str | None = None) -> JsonObject:
        if isinstance(payload, dict) and payload.get("task") == "blocking_drift_classification":
            return self._handle_blocking_drift(payload, request_id=request_id)
        if isinstance(payload, dict) and payload.get("task") == "review":
            return self._handle_review(payload, request_id=request_id)

        try:
            request = ProposalRequest.model_validate(payload)
        except ValidationError as exc:
            message = exc.errors()[0].get("msg", "validation failed")
            return skip(f"Malformed PR Guard request: {message}.")

        size_skip = self._validate_input_sizes(request)
        if size_skip is not None:
            return size_skip

        self._enforce_repo_allowlist(request)

        boundary_skip = self._validate_task_boundary(request)
        if boundary_skip is not None:
            return boundary_skip

        cache_key = request_id or compute_idempotency_key(request, self.config)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            content = self.hermes_client.complete_json(build_messages(request))
        except httpx.TimeoutException:
            result: JsonObject = skip("Hermes proposal timed out; leaving drift for human review.")
        except Exception:
            result = skip("Hermes proposal failed; leaving drift for human review.")
        else:
            try:
                proposal = parse_model_proposal(content)
            except ValueError as exc:
                result = skip(f"Malformed Hermes proposal: {exc}.")
            else:
                result = validate_proposal(proposal, request=request)

        if self.cache is not None:
            self.cache.set(cache_key, result)
        return result

    def _handle_blocking_drift(
        self,
        payload: object,
        *,
        request_id: str | None = None,
    ) -> JsonObject:
        try:
            request = BlockingDriftRequest.model_validate(payload)
        except ValidationError:
            return {"blocking": []}

        if len(request.diff_summary) > self.config.max_diff_summary_chars:
            return {"blocking": []}
        if not request.advisory_drifts:
            return {"blocking": []}

        self._enforce_repo_allowlist_for_metadata(request.metadata)

        cache_key = request_id or compute_blocking_idempotency_key(request, self.config)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            content = self.hermes_client.complete_json(build_blocking_messages(request))
        except Exception:
            result: JsonObject = {"blocking": []}
        else:
            try:
                decision = parse_model_proposal(content)
            except ValueError:
                result = {"blocking": []}
            else:
                result = validate_blocking_decision(decision, request=request)

        if self.cache is not None:
            self.cache.set(cache_key, result)
        return result

    def _handle_review(
        self,
        payload: object,
        *,
        request_id: str | None = None,
    ) -> JsonObject:
        try:
            request = ReviewRequest.model_validate(payload)
        except ValidationError:
            return _unknown_review("Malformed review request.")

        if (
            len(request.diff_summary) > self.config.max_diff_summary_chars
            or len(request.repo_context) > self.config.max_repo_context_chars
        ):
            return _unknown_review("review input too large.")

        self._enforce_repo_allowlist_for_metadata(request.metadata)

        cache_key = request_id or compute_review_idempotency_key(request, self.config)
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        try:
            content = self.hermes_client.complete_json(build_review_messages(request))
        except Exception:
            result: JsonObject = _unknown_review("Hermes review failed; leaving review to humans.")
        else:
            try:
                report = parse_model_proposal(content)
            except ValueError:
                result = _unknown_review("Malformed Hermes review.")
            else:
                result = _normalize_review_report(report)

        if self.cache is not None:
            self.cache.set(cache_key, result)
        return result

    def _validate_input_sizes(self, request: ProposalRequest) -> JsonObject | None:
        seed_too_large = (
            request.seed_md_text is not None
            and len(request.seed_md_text) > self.config.max_seed_chars
        )
        if seed_too_large:
            return skip("seed_md_text is too large for synchronous Hermes proposal generation.")
        repo_context_too_large = (
            request.repo_context is not None
            and len(request.repo_context) > self.config.max_repo_context_chars
        )
        if repo_context_too_large:
            return skip("repo_context is too large for synchronous Hermes proposal generation.")
        return None

    def _enforce_repo_allowlist(self, request: ProposalRequest) -> None:
        self._enforce_repo_allowlist_for_metadata(request.metadata)

    def _enforce_repo_allowlist_for_metadata(self, metadata: Metadata) -> None:
        repo = metadata.repo or self.config.single_repo_mode
        if repo is None:
            raise ForbiddenRequest(
                "metadata.repo is required unless single_repo_mode is configured"
            )

        allowed = set(self.config.allowed_repos)
        if self.config.single_repo_mode:
            allowed.add(self.config.single_repo_mode)
        if not allowed:
            raise ForbiddenRequest("adapter has no allowed repositories configured")
        if repo not in allowed:
            raise ForbiddenRequest(f"repository is not allowed: {repo}")

    @staticmethod
    def _validate_task_boundary(request: ProposalRequest) -> JsonObject | None:
        if request.task == "seed_fix" and request.drift.source != "seed":
            return skip("seed_fix requires seed drift source.")
        if request.task == "code_fix" and request.drift.source != "prd":
            return skip("code_fix requires prd drift source.")
        if request.task not in {"seed_fix", "code_fix"}:
            return skip(f"Unsupported task: {request.task}.")
        return None


def build_messages(request: ProposalRequest) -> list[dict[str, str]]:
    payload_json = json.dumps(
        request.prompt_payload(), ensure_ascii=False, sort_keys=True, indent=2
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Task: {request.task}\n"
                f"PR Guard request JSON:\n{payload_json}\n\n"
                "Return JSON only."
            ),
        },
    ]


def build_blocking_messages(request: BlockingDriftRequest) -> list[dict[str, str]]:
    payload_json = json.dumps(
        request.prompt_payload(), ensure_ascii=False, sort_keys=True, indent=2
    )
    return [
        {"role": "system", "content": BLOCKING_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Task: blocking_drift_classification\n"
                f"PR Guard request JSON:\n{payload_json}\n\n"
                "Return JSON only."
            ),
        },
    ]


def build_review_messages(request: ReviewRequest) -> list[dict[str, str]]:
    payload_json = json.dumps(
        request.prompt_payload(), ensure_ascii=False, sort_keys=True, indent=2
    )
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Task: review\n"
                f"PR Guard request JSON:\n{payload_json}\n\n"
                "Return JSON only."
            ),
        },
    ]


def _unknown_review(reason: str) -> JsonObject:
    return {"score": -1, "summary": reason, "findings": []}


def _coerce_review_score(raw_score: object) -> int:
    """Coerce a model score to 0-5, or -1 (unknown).

    Mirrors pr_guard._parse_score so harmless formatting drift (e.g. the score
    arriving as "4" or 4.0) is preserved instead of collapsing to UNKNOWN on the
    Hermes path. bool is rejected; a negative score is the unknown sentinel.
    """
    if isinstance(raw_score, bool):
        return -1
    try:
        score = int(raw_score)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1
    if score < 0:
        return -1
    return min(5, score)


def _normalize_review_report(report: JsonObject) -> JsonObject:
    score = _coerce_review_score(report.get("score"))

    summary = report.get("summary")
    if not isinstance(summary, str):
        summary = ""

    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []

    return {"score": score, "summary": summary, "findings": findings}


def compute_idempotency_key(request: ProposalRequest, config: AdapterConfig) -> str:
    metadata = request.metadata
    parts = [
        metadata.repo or config.single_repo_mode or "",
        str(metadata.pr_number or ""),
        metadata.head_sha or metadata.head_ref or "",
        request.task,
        request.drift.source_file or "",
        str(request.drift.line or ""),
        request.drift.quote,
    ]
    raw = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_blocking_idempotency_key(
    request: BlockingDriftRequest,
    config: AdapterConfig,
) -> str:
    metadata = request.metadata
    drift_fingerprint = "|".join(
        f"{drift.source_file or ''}:{drift.line or ''}:{drift.quote}"
        for drift in request.advisory_drifts
    )
    parts = [
        metadata.repo or config.single_repo_mode or "",
        str(metadata.pr_number or ""),
        metadata.head_sha or metadata.head_ref or "",
        request.task,
        drift_fingerprint,
        request.diff_summary,
    ]
    raw = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_review_idempotency_key(
    request: ReviewRequest,
    config: AdapterConfig,
) -> str:
    metadata = request.metadata
    parts = [
        metadata.repo or config.single_repo_mode or "",
        str(metadata.pr_number or ""),
        metadata.head_sha or metadata.head_ref or "",
        request.task,
        request.diff_summary,
        request.repo_context,
    ]
    raw = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
