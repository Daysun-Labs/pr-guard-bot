"""GitHub API client factory.

Sub-AC 1: 인증된 octokit(여기선 httpx 기반) 인스턴스를 생성/주입하는
client factory. 토큰은 인자로 받거나 GITHUB_TOKEN 환경변수로부터 읽는다.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_ACCEPT = "application/vnd.github+json"
DEFAULT_API_VERSION = "2022-11-28"
USER_AGENT = "pr-guard-bot"


def create_github_client(
    token: Optional[str] = None,
    *,
    base_url: str = GITHUB_API_BASE,
    transport: Optional[httpx.BaseTransport] = None,
    timeout: float = 10.0,
) -> httpx.Client:
    """Create an authenticated httpx.Client for the GitHub REST API.

    Args:
        token: GitHub token. Falls back to GITHUB_TOKEN env var.
        base_url: GitHub API base URL (override for GHE).
        transport: Optional httpx transport for injection/testing.
        timeout: Per-request timeout in seconds.

    Returns:
        httpx.Client with Authorization, Accept, X-GitHub-Api-Version,
        and User-Agent headers preset.

    Raises:
        ValueError: when no token is provided and GITHUB_TOKEN is unset.
    """
    resolved = token if token is not None else os.environ.get("GITHUB_TOKEN")
    if not resolved:
        raise ValueError(
            "GitHub token required: pass token=... or set GITHUB_TOKEN env var."
        )

    headers = {
        "Authorization": f"Bearer {resolved}",
        "Accept": DEFAULT_ACCEPT,
        "X-GitHub-Api-Version": DEFAULT_API_VERSION,
        "User-Agent": USER_AGENT,
    }

    return httpx.Client(
        base_url=base_url,
        headers=headers,
        transport=transport,
        timeout=timeout,
    )
