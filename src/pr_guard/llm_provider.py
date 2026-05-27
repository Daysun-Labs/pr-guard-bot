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

from .drift import DriftItem
from .patcher import (
    DEFAULT_MODEL,
    PatchProposal,
    _parse_proposal,
    _slug,
    generate_code_fix_proposal,
    generate_seed_fix,
)


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
    ) -> None:
        if not webhook_url.strip():
            raise ValueError("webhook_url is required")
        self.webhook_url = webhook_url
        self.http_client = http_client or httpx.Client()
        self.timeout = timeout
        self.token = token.strip() if token else None

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

    def _post(self, payload: dict[str, Any]) -> Any:
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
) -> LLMProvider | None:
    hermes_url = (env.get("HERMES_PR_GUARD_WEBHOOK_URL") or "").strip()
    if hermes_url:
        return HermesWebhookProvider(
            hermes_url,
            http_client=http_client,
            token=env.get("HERMES_PR_GUARD_WEBHOOK_TOKEN"),
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
