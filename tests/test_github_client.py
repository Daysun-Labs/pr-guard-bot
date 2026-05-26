"""Unit tests for github_client.create_github_client (Sub-AC 1)."""

from __future__ import annotations

import httpx
import pytest

from pr_guard.github_client import (
    DEFAULT_ACCEPT,
    DEFAULT_API_VERSION,
    GITHUB_API_BASE,
    USER_AGENT,
    create_github_client,
)


def _capture_transport():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json={"ok": True})

    return httpx.MockTransport(handler), captured


def test_factory_sets_auth_and_headers_with_explicit_token():
    transport, captured = _capture_transport()
    client = create_github_client(token="ghp_mocktoken123", transport=transport)

    try:
        resp = client.get("/rate_limit")
    finally:
        client.close()

    assert resp.status_code == 200
    req = captured["request"]
    assert req.headers["Authorization"] == "Bearer ghp_mocktoken123"
    assert req.headers["Accept"] == DEFAULT_ACCEPT
    assert req.headers["X-GitHub-Api-Version"] == DEFAULT_API_VERSION
    assert req.headers["User-Agent"] == USER_AGENT
    assert str(req.url) == f"{GITHUB_API_BASE}/rate_limit"


def test_factory_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env_token_xyz")
    transport, captured = _capture_transport()
    client = create_github_client(transport=transport)
    try:
        client.get("/user")
    finally:
        client.close()
    assert captured["request"].headers["Authorization"] == "Bearer env_token_xyz"


def test_factory_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="GitHub token required"):
        create_github_client()


def test_factory_respects_custom_base_url():
    transport, captured = _capture_transport()
    client = create_github_client(
        token="t", base_url="https://ghe.example.com/api/v3", transport=transport
    )
    try:
        client.get("/repos/o/r")
    finally:
        client.close()
    assert str(captured["request"].url) == "https://ghe.example.com/api/v3/repos/o/r"
