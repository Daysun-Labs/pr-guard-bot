from __future__ import annotations

import json

import httpx

from pr_guard.github_client import create_github_client
from pr_guard.main import OctokitAdapter


def test_octokit_adapter_supplies_existing_file_sha_for_contents_update() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "GET":
            assert request.url.params.get("ref") == "pr-guard/seed-fix/example"
            return httpx.Response(200, json={"sha": "existing-sha"})
        if request.method == "PUT":
            assert body is not None
            assert body["sha"] == "existing-sha"
            return httpx.Response(200, json={"commit": {"sha": "new-commit"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = create_github_client("ghp_test", transport=httpx.MockTransport(handler))
    octokit = OctokitAdapter(client)

    result = octokit.repos.create_or_update_file_contents(
        owner="octo",
        repo="app",
        path="SEED.md",
        message="docs(seed): align spec",
        content="IyBTRUVEK",
        branch="pr-guard/seed-fix/example",
    )

    assert result == {"commit": {"sha": "new-commit"}}
    assert [method for method, _, _ in seen] == ["GET", "PUT"]


def test_octokit_adapter_omits_sha_when_contents_file_is_new() -> None:
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode()) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        if request.method == "PUT":
            assert body is not None
            assert "sha" not in body
            return httpx.Response(201, json={"commit": {"sha": "new-commit"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = create_github_client("ghp_test", transport=httpx.MockTransport(handler))
    octokit = OctokitAdapter(client)

    result = octokit.repos.create_or_update_file_contents(
        owner="octo",
        repo="app",
        path="docs/pr-guard-proposals/example.md",
        message="docs: add proposal",
        content="IyBQcm9wb3NhbAo=",
        branch="pr-guard/code-fix/example",
    )

    assert result == {"commit": {"sha": "new-commit"}}
    assert [method for method, _, _ in seen] == ["GET", "PUT"]
