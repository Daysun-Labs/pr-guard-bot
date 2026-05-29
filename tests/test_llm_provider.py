from __future__ import annotations

import json
from typing import Any

import httpx

from pr_guard.drift import DriftItem
from pr_guard.llm_provider import (
    AnthropicProvider,
    HermesWebhookProvider,
    resolve_llm_provider,
)
from pr_guard.patcher import PatchProposal


def _drift(*, source: str = "seed") -> DriftItem:
    return DriftItem(
        type="missing_requirement",
        severity="high",
        source=source,
        source_file=f"{source.upper()}.md",
        section="Acceptance",
        kind="acceptance",
        quote="Add OAuth login",
        line=12,
        score=0.55,
    )


class CapturingHttpClient:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.requests: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self.requests.append({"url": url, "json": json, "timeout": timeout, "headers": headers})
        return httpx.Response(
            self.status_code,
            json=self.payload,
            request=httpx.Request("POST", url),
        )


def test_resolve_prefers_hermes_webhook_over_anthropic() -> None:
    http = CapturingHttpClient({"action": "skip"})
    provider = resolve_llm_provider(
        {
            "HERMES_PR_GUARD_WEBHOOK_URL": "https://hermes.example/pr-guard",
            "HERMES_PR_GUARD_WEBHOOK_TOKEN": "secret-token",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        },
        http_client=http,
    )

    assert isinstance(provider, HermesWebhookProvider)
    provider.generate_seed_fix(_drift(source="seed"), seed_md_text="# SEED\n")
    assert http.requests[0]["headers"] == {"Authorization": "Bearer secret-token"}


def test_resolve_returns_anthropic_fallback_when_only_key_present() -> None:
    provider = resolve_llm_provider({"ANTHROPIC_API_KEY": "sk-ant-test"})

    assert isinstance(provider, AnthropicProvider)


def test_resolve_returns_none_without_provider_configuration() -> None:
    assert resolve_llm_provider({}) is None


def test_hermes_seed_fix_posts_context_and_parses_update() -> None:
    http = CapturingHttpClient(
        {
            "action": "update",
            "new_content": "# SEED\nOAuth via Hermes\n",
            "message": "docs(seed): align OAuth setup",
            "rationale": "Hermes OAuth is the intended integration path.",
        }
    )
    provider = HermesWebhookProvider("https://hermes.example/pr-guard", http_client=http)

    proposal = provider.generate_seed_fix(_drift(source="seed"), seed_md_text="# SEED\nold\n")

    assert isinstance(proposal, PatchProposal)
    assert proposal.change.path == "SEED.md"
    assert proposal.change.content == "# SEED\nOAuth via Hermes\n"
    assert proposal.change.message == "docs(seed): align OAuth setup"
    assert proposal.rationale.startswith("Hermes OAuth")
    assert http.requests[0]["url"] == "https://hermes.example/pr-guard"
    assert http.requests[0]["json"]["task"] == "seed_fix"
    assert http.requests[0]["json"]["drift"] == _drift(source="seed").to_dict()
    assert http.requests[0]["json"]["seed_md_text"] == "# SEED\nold\n"


def test_hermes_code_fix_posts_context_and_parses_nested_proposal() -> None:
    payload = {
        "proposal": {
            "action": "update",
            "new_content": "# Proposal\n\nUse Hermes webhook provider.\n",
            "message": "docs: propose Hermes integration",
            "rationale": "Keeps OAuth behind Hermes.",
        }
    }
    http = CapturingHttpClient(payload)
    provider = HermesWebhookProvider("https://hermes.example/pr-guard", http_client=http)

    proposal = provider.generate_code_fix_proposal(
        _drift(source="prd"), repo_context="src/pr_guard/main.py\n"
    )

    assert proposal is not None
    assert proposal.change.path.startswith("docs/pr-guard-proposals/")
    assert proposal.change.path.endswith(".md")
    assert proposal.change.content.startswith("# Proposal")
    assert http.requests[0]["json"]["task"] == "code_fix"
    assert http.requests[0]["json"]["repo_context"] == "src/pr_guard/main.py\n"


def test_hermes_blocking_classifier_posts_advisory_context_and_parses_indexes() -> None:
    http = CapturingHttpClient({"blocking": [{"index": 0, "reason": "real missing flow"}]})
    provider = HermesWebhookProvider("https://hermes.example/pr-guard", http_client=http)
    drift = _drift(source="prd")

    blocking = provider.classify_blocking_drift([drift], diff_summary="FILE src/app.py")

    assert blocking == [drift]
    request_json = http.requests[0]["json"]
    assert request_json["task"] == "blocking_drift_classification"
    assert request_json["schema_version"] == "pr-guard.blocking-drift/v1"
    assert request_json["advisory_drifts"] == [drift.to_dict()]
    assert request_json["diff_summary"] == "FILE src/app.py"


def test_anthropic_blocking_classifier_parses_json_response() -> None:
    class FakeMessages:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> dict[str, Any]:
            self.requests.append(kwargs)
            return {"content": [{"text": json.dumps({"blocking": [{"index": 1}]})}]}

    class FakeClient:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    client = FakeClient()
    provider = AnthropicProvider("sk-ant-test", client=client)
    first = _drift(source="prd")
    second = _drift(source="seed")

    blocking = provider.classify_blocking_drift([first, second], diff_summary="FILE src/app.py")

    assert blocking == [second]
    user_payload = json.loads(client.messages.requests[0]["messages"][0]["content"])
    assert user_payload["schema_version"] == "pr-guard.blocking-drift/v1"
    assert user_payload["advisory_drifts"][1]["index"] == 1
    assert user_payload["diff_summary"] == "FILE src/app.py"


def test_hermes_payload_includes_metadata_when_configured() -> None:
    http = CapturingHttpClient({"action": "skip", "reason": "test"})
    provider = HermesWebhookProvider(
        "https://hermes.example/pr-guard",
        http_client=http,
        repo="Daysun-Labs/astate-brain",
        pr_number=42,
        base_ref="main",
        head_ref="feature/x",
        head_sha="abc123",
    )

    provider.generate_code_fix_proposal(_drift(source="prd"), repo_context="tree\n")

    request_json = http.requests[0]["json"]
    assert request_json["schema_version"] == "pr-guard.hermes-proposal/v1"
    assert request_json["metadata"] == {
        "repo": "Daysun-Labs/astate-brain",
        "pr_number": 42,
        "base_ref": "main",
        "head_ref": "feature/x",
        "head_sha": "abc123",
    }


def test_resolve_passes_metadata_to_hermes_provider() -> None:
    http = CapturingHttpClient({"action": "skip", "reason": "test"})
    provider = resolve_llm_provider(
        {"HERMES_PR_GUARD_WEBHOOK_URL": "https://hermes.example/pr-guard"},
        http_client=http,
        metadata={"repo": "Daysun-Labs/astate-brain", "pr_number": 42},
    )

    assert isinstance(provider, HermesWebhookProvider)
    provider.generate_seed_fix(_drift(source="seed"), seed_md_text="# SEED\n")
    assert http.requests[0]["json"]["metadata"] == {
        "repo": "Daysun-Labs/astate-brain",
        "pr_number": 42,
    }


def test_hermes_returns_none_on_skip_or_malformed_response() -> None:
    skipped = HermesWebhookProvider(
        "https://hermes.example/pr-guard",
        http_client=CapturingHttpClient({"action": "skip", "reason": "too vague"}),
    )
    malformed = HermesWebhookProvider(
        "https://hermes.example/pr-guard",
        http_client=CapturingHttpClient({"unexpected": "shape"}),
    )

    assert skipped.generate_seed_fix(_drift(), seed_md_text="x") is None
    assert malformed.generate_seed_fix(_drift(), seed_md_text="x") is None
