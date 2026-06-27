"""LLM/fix proposal provider abstraction for PR Guard.

Hermes webhook is preferred for managed OAuth/LLM connectivity. Direct Anthropic
usage remains as a backwards-compatible fallback and is intentionally isolated in
this module so the CLI entrypoint does not import Anthropic directly.
"""
from __future__ import annotations

import importlib
import json
from typing import Any, Mapping, Optional, Protocol

import httpx

from .drift import BlockingDriftDecision, DriftItem
from .patcher import (
    DEFAULT_MODEL,
    PatchProposal,
    _FENCE_RE,
    _extract_text,
    _parse_proposal,
    _slug,
    generate_code_fix_proposal,
    generate_seed_fix,
)
from .review import ReviewReport, build_review_payload, parse_review_response, review_diff_via_client

PROPOSAL_SCHEMA_VERSION = "pr-guard.hermes-proposal/v1"
BLOCKING_SCHEMA_VERSION = "pr-guard.blocking-drift/v1"


class LLMProvider(Protocol):
    def generate_seed_fix(
        self,
        drift: DriftItem,
        *,
        seed_md_text: str,
        seed_md_path: str = "SEED.md",
    ) -> Optional[PatchProposal]: ...

    def generate_code_fix_proposal(
        self,
        drift: DriftItem,
        *,
        repo_context: str,
        proposals_dir: str = "docs/pr-guard-proposals",
    ) -> Optional[PatchProposal]: ...

    def classify_blocking_drift(
        self,
        advisory: list[DriftItem],
        *,
        diff_summary: str | None = None,
    ) -> list[BlockingDriftDecision]: ...

    def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response: ...


class _AnthropicMessagesAdapter:
    """patcher.ClaudeClient Protocol (has .create) → anthropic SDK shape."""

    def __init__(self, anthropic_client: Any) -> None:
        self._client = anthropic_client

    def create(self, **kwargs: Any) -> Any:
        return self._client.messages.create(**kwargs)


class AnthropicProvider:
    """Backward-compatible direct Anthropic provider.

    The SDK import is delayed until a proposal is actually requested so tests and
    dry-run CLI paths can resolve the provider without performing SDK setup.
    """

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, client: Any | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    def generate_seed_fix(
        self,
        drift: DriftItem,
        *,
        seed_md_text: str,
        seed_md_path: str = "SEED.md",
    ) -> Optional[PatchProposal]:
        return generate_seed_fix(
            drift,
            seed_md_text=seed_md_text,
            client=self._claude(),
            seed_md_path=seed_md_path,
            model=self.model,
        )

    def generate_code_fix_proposal(
        self,
        drift: DriftItem,
        *,
        repo_context: str,
        proposals_dir: str = "docs/pr-guard-proposals",
    ) -> Optional[PatchProposal]:
        return generate_code_fix_proposal(
            drift,
            repo_context=repo_context,
            client=self._claude(),
            proposals_dir=proposals_dir,
            model=self.model,
        )

    def classify_blocking_drift(
        self,
        advisory: list[DriftItem],
        *,
        diff_summary: str | None = None,
    ) -> list[BlockingDriftDecision]:
        if not advisory:
            return []
        resp = _call_blocking_classifier(
            self._claude(),
            advisory=advisory,
            diff_summary=diff_summary,
            model=self.model,
        )
        return _select_blocking_from_response(resp, advisory)

    def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport:
        return review_diff_via_client(
            self._claude(),
            diff_summary=diff_summary,
            repo_context=repo_context,
            model=self.model,
        )

    def _claude(self) -> _AnthropicMessagesAdapter:
        if self._client is None:
            try:
                anthropic_module = importlib.import_module("anthropic")
                Anthropic = getattr(anthropic_module, "Anthropic")
            except (ImportError, AttributeError) as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is set but the optional 'anthropic' package is not installed. "
                    "Install pr-guard with the [anthropic] extra or configure HERMES_PR_GUARD_WEBHOOK_URL."
                ) from exc

            self._client = Anthropic(api_key=self.api_key)
        return _AnthropicMessagesAdapter(self._client)


class HermesWebhookProvider:
    """Hermes-backed provider that POSTs drift context to a webhook endpoint."""

    def __init__(
        self,
        webhook_url: str,
        *,
        http_client: HttpClient | None = None,
        timeout: float = 30.0,
        token: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        repo: str | None = None,
        pr_number: int | None = None,
        base_ref: str | None = None,
        head_ref: str | None = None,
        head_sha: str | None = None,
    ) -> None:
        if not webhook_url.strip():
            raise ValueError("webhook_url is required")
        self.webhook_url = webhook_url
        self.http_client = http_client or httpx.Client()
        self.timeout = timeout
        self.token = token.strip() if token else None
        typed_metadata = {
            "repo": repo,
            "pr_number": pr_number,
            "base_ref": base_ref,
            "head_ref": head_ref,
            "head_sha": head_sha,
        }
        merged_metadata: dict[str, Any] = {
            key: value for key, value in typed_metadata.items() if value is not None
        }
        if metadata:
            merged_metadata.update(
                {key: value for key, value in metadata.items() if value is not None}
            )
        self.metadata = merged_metadata

    def generate_seed_fix(
        self,
        drift: DriftItem,
        *,
        seed_md_text: str,
        seed_md_path: str = "SEED.md",
    ) -> Optional[PatchProposal]:
        data = self._post(
            {
                "task": "seed_fix",
                "drift": drift.to_dict(),
                "seed_md_text": seed_md_text,
                "seed_md_path": seed_md_path,
                "proposal_shape": ["action", "new_content", "message", "rationale"],
            }
        )
        return _parse_webhook_proposal(data, file_path=seed_md_path)

    def generate_code_fix_proposal(
        self,
        drift: DriftItem,
        *,
        repo_context: str,
        proposals_dir: str = "docs/pr-guard-proposals",
    ) -> Optional[PatchProposal]:
        path = f"{proposals_dir}/{_slug(drift)}.md"
        data = self._post(
            {
                "task": "code_fix",
                "drift": drift.to_dict(),
                "repo_context": repo_context,
                "output_path": path,
                "proposal_shape": ["action", "new_content", "message", "rationale"],
            }
        )
        return _parse_webhook_proposal(data, file_path=path)

    def classify_blocking_drift(
        self,
        advisory: list[DriftItem],
        *,
        diff_summary: str | None = None,
    ) -> list[BlockingDriftDecision]:
        if not advisory:
            return []
        data = self._post(
            {
                "task": "blocking_drift_classification",
                "schema_version": BLOCKING_SCHEMA_VERSION,
                "advisory_drifts": [drift.to_dict() for drift in advisory],
                "diff_summary": diff_summary or "",
                "decision_shape": {
                    "blocking": [
                        {
                            "index": 0,
                            "reason": "why this scoped advisory finding is real blocking drift",
                        }
                    ]
                },
            }
        )
        return _select_blocking_from_response(data, advisory)

    def review_diff(self, *, diff_summary: str, repo_context: str) -> ReviewReport:
        data = self._post(
            {
                "task": "review",
                **build_review_payload(diff_summary=diff_summary, repo_context=repo_context),
                "report_shape": {
                    "score": "int 0-5",
                    "summary": "str",
                    "findings": [
                        {
                            "category": "bug|security|trust_boundary|perf|quality",
                            "severity": "error|warn|info",
                            "file": "str",
                            "line": "int",
                            "quote": "str",
                            "suggestion": "str",
                        }
                    ],
                },
            }
        )
        return parse_review_response(data)

    def _post(self, payload: dict[str, Any]) -> Any:
        if self.metadata:
            payload = {
                "schema_version": PROPOSAL_SCHEMA_VERSION,
                "metadata": self.metadata,
                **payload,
            }
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        response = self.http_client.post(
            self.webhook_url,
            json=payload,
            timeout=self.timeout,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


def resolve_llm_provider(
    env: Mapping[str, str | None],
    *,
    http_client: HttpClient | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> LLMProvider | None:
    hermes_url = (env.get("HERMES_PR_GUARD_WEBHOOK_URL") or "").strip()
    if hermes_url:
        return HermesWebhookProvider(
            hermes_url,
            http_client=http_client,
            token=env.get("HERMES_PR_GUARD_WEBHOOK_TOKEN"),
            metadata=metadata,
        )

    anthropic_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if anthropic_key:
        return AnthropicProvider(anthropic_key)

    return None


def _parse_webhook_proposal(data: Any, *, file_path: str) -> Optional[PatchProposal]:
    """Parse direct or nested webhook responses using patcher's proposal parser."""
    proposal = data.get("proposal") if isinstance(data, dict) and "proposal" in data else data

    if isinstance(proposal, dict):
        text = json.dumps(proposal)
    elif isinstance(proposal, str):
        text = proposal
    else:
        return None

    return _parse_proposal({"content": [{"text": text}]}, file_path=file_path)


_SYSTEM_BLOCKING_DRIFT = """\
You are pr-guard's semantic blocking drift classifier.

The static matcher has already produced scoped advisory drift. Your job is only
to decide which advisory items should fail CI. Be conservative:

- Return blocking only when the diff is clearly scoped to the requirement area
  and the requirement is still genuinely missing or contradicted.
- Do not block on generic vocabulary overlap, docs/config-only changes,
  ambiguous requirements, or cases where the diff lacks enough context.
- If uncertain, return no blocking items.

OUTPUT JSON ONLY:

{"blocking": [{"index": 0, "reason": "<short evidence-based reason>"}]}

or:

{"blocking": []}
"""


def _call_blocking_classifier(
    client: Any,
    *,
    advisory: list[DriftItem],
    diff_summary: str | None,
    model: str,
) -> Any:
    payload = {
        "schema_version": BLOCKING_SCHEMA_VERSION,
        "advisory_drifts": [
            {"index": index, **drift.to_dict()} for index, drift in enumerate(advisory)
        ],
        "diff_summary": diff_summary or "",
    }
    return client.create(
        model=model,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_BLOCKING_DRIFT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )


def _select_blocking_from_response(
    data: Any,
    advisory: list[DriftItem],
) -> list[BlockingDriftDecision]:
    decisions = _parse_blocking_decisions(data, item_count=len(advisory))
    return [
        BlockingDriftDecision(
            drift=advisory[index],
            reason=reason,
            source="semantic",
        )
        for index, reason in decisions
    ]


def _parse_blocking_decisions(data: Any, *, item_count: int) -> list[tuple[int, str]]:
    if not item_count:
        return []

    if isinstance(data, dict) and not any(
        key in data for key in ("blocking", "blocking_indexes", "classification")
    ):
        text = _extract_text(data).strip()
        if text:
            m = _FENCE_RE.match(text)
            if m:
                text = m.group(1).strip()
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return []

    if not isinstance(data, dict):
        text = _extract_text(data).strip()
        if not text:
            return []
        m = _FENCE_RE.match(text)
        if m:
            text = m.group(1).strip()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []

    if not isinstance(data, dict):
        return []
    if isinstance(data.get("classification"), dict):
        data = data["classification"]

    entries = data.get("blocking_indexes")
    if entries is None:
        entries = data.get("blocking")
    if not isinstance(entries, list):
        return []

    decisions: list[tuple[int, str]] = []
    for entry in entries:
        index: int | None = None
        reason = ""
        if isinstance(entry, int):
            index = entry
        elif isinstance(entry, dict):
            raw_index = entry.get("index")
            if isinstance(raw_index, int):
                index = raw_index
            reason = str(entry.get("reason") or entry.get("evidence") or "").strip()
            decision = str(entry.get("decision", "blocking")).lower()
            if decision not in {"blocking", "block", "true", "yes"}:
                index = None

        if (
            index is None
            or index < 0
            or index >= item_count
            or any(existing == index for existing, _ in decisions)
        ):
            continue
        decisions.append((index, reason or "Classified as blocking by semantic provider."))
    return decisions
