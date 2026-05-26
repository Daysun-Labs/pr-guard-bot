"""Unit tests for publish.publish_pr_comment (Sub-AC 2)."""

from __future__ import annotations

import json

import httpx
import pytest

from pr_guard.github_client import create_github_client
from pr_guard.publish import PublishError, publish_pr_comment


def _make_client(handler):
    transport = httpx.MockTransport(handler)
    return create_github_client(token="ghp_test", transport=transport)


def test_publish_pr_comment_posts_to_correct_endpoint_with_body():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(
            201,
            json={"id": 42, "body": captured["body"]["body"], "html_url": "https://x"},
        )

    client = _make_client(handler)
    result = publish_pr_comment(
        client,
        owner="octocat",
        repo="hello",
        pr_number=7,
        body="drift detected",
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/repos/octocat/hello/issues/7/comments")
    assert captured["body"] == {"body": "drift detected"}
    assert captured["auth"] == "Bearer ghp_test"
    assert result["id"] == 42


def test_publish_pr_comment_raises_publish_error_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _make_client(handler)
    with pytest.raises(PublishError) as exc:
        publish_pr_comment(
            client, owner="o", repo="r", pr_number=1, body="hi"
        )
    assert exc.value.status_code == 404
    assert "Not Found" in exc.value.message


def test_publish_pr_comment_raises_publish_error_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _make_client(handler)
    with pytest.raises(PublishError) as exc:
        publish_pr_comment(client, owner="o", repo="r", pr_number=1, body="hi")
    assert exc.value.status_code == 500


@pytest.mark.parametrize(
    "kwargs",
    [
        {"owner": "", "repo": "r", "pr_number": 1, "body": "x"},
        {"owner": "o", "repo": "", "pr_number": 1, "body": "x"},
        {"owner": "o", "repo": "r", "pr_number": 0, "body": "x"},
        {"owner": "o", "repo": "r", "pr_number": -3, "body": "x"},
        {"owner": "o", "repo": "r", "pr_number": 1, "body": ""},
        {"owner": "o", "repo": "r", "pr_number": 1, "body": "   "},
    ],
)
def test_publish_pr_comment_validates_inputs(kwargs):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(201, json={})

    client = _make_client(handler)
    with pytest.raises(ValueError):
        publish_pr_comment(client, **kwargs)


def test_publish_pr_comment_returns_parsed_json_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 99})

    client = _make_client(handler)
    result = publish_pr_comment(
        client, owner="o", repo="r", pr_number=5, body="ok"
    )
    assert result == {"id": 99}


def test_publish_pr_comment_updates_existing_marker_comment():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 101, "body": "<!-- pr-guard:drift-report -->\nold report"},
                    {"id": 202, "body": "unrelated"},
                ],
            )
        if request.method == "PATCH":
            payload = json.loads(request.content.decode())
            return httpx.Response(200, json={"id": 101, "body": payload["body"]})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = _make_client(handler)
    result = publish_pr_comment(
        client,
        owner="octocat",
        repo="hello",
        pr_number=7,
        body="new report",
        marker="<!-- pr-guard:drift-report -->",
    )

    assert seen == [
        ("GET", "/repos/octocat/hello/issues/7/comments"),
        ("PATCH", "/repos/octocat/hello/issues/comments/101"),
    ]
    assert result["body"] == "<!-- pr-guard:drift-report -->\nnew report"
