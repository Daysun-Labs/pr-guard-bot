from __future__ import annotations

from pr_guard_adapter.app import config_from_env


def test_config_from_env_accepts_timeout_override() -> None:
    cfg = config_from_env(
        {
            "PR_GUARD_ALLOWED_REPOS": "Daysun-Labs/astate-brain",
            "HERMES_API_URL": "http://127.0.0.1:8647",
            "HERMES_API_KEY": "test-key",
            "HERMES_PR_GUARD_MODEL": "ds-pr-guard",
            "HERMES_TIMEOUT_SECONDS": "7.5",
            "PR_GUARD_ADAPTER_TOKEN": "adapter-token",
        }
    )

    assert cfg.allowed_repos == {"Daysun-Labs/astate-brain"}
    assert cfg.hermes_api_url == "http://127.0.0.1:8647"
    assert cfg.hermes_api_key == "test-key"
    assert cfg.model == "ds-pr-guard"
    assert cfg.hermes_timeout == 7.5
    assert cfg.adapter_token == "adapter-token"


def test_config_from_env_ignores_invalid_timeout_override() -> None:
    cfg = config_from_env({"HERMES_TIMEOUT_SECONDS": "not-a-number"})

    assert cfg.hermes_timeout == 20.0
