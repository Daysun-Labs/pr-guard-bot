"""Generate fix-PR patches via Claude.

Two flavors:
  - generate_seed_fix(drift, seed_md_text, client)
      → SEED.md 전체를 갱신하는 FileChange. 봇이 spec을 코드 현실에 맞춰 조정.
  - generate_code_fix_proposal(drift, repo_context, client)
      → docs/pr-guard-proposals/<slug>.md 마크다운. 코드 직접 수정 X — 사람이
        검토 후 반영하기 좋은 형태의 분석/제안 문서.

Claude 클라이언트는 ``ClaudeClient`` Protocol로 DI 받아 unit-test 가능.
실제 호출은 anthropic SDK의 ``client.messages.create(**kw)`` 시그니처를
래핑한 어댑터를 main.py에서 주입한다.

응답 파싱 규칙:
  Claude는 JSON-only로 응답 (system prompt에 명시).
  허용 형식:
    {"action": "update", "new_content": "...", "message": "...", "rationale": "..."}
    {"action": "skip",   "reason": "..."}
  Code-fence ```json ... ``` 으로 감싸도 허용.
  파싱 실패 / action != update / new_content 비어있음 → None 반환 (no-op).

프롬프트 캐싱: 5분 TTL ephemeral 캐시를 system 메시지에 적용해
같은 PR 안에서 여러 fix 생성 시 토큰 비용 절감.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Protocol

from .commit import FileChange
from .drift import DriftItem


DEFAULT_MODEL = "claude-sonnet-4-5"  # patcher는 sonnet으로 충분. opus는 비용·지연 비효율.
DEFAULT_MAX_TOKENS = 8192


class ClaudeClient(Protocol):
    """Minimal shape compatible with anthropic SDK's ``client.messages.create``."""

    def create(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class PatchProposal:
    """Claude가 제안한 단일 파일 변경 + PR 본문에 들어갈 설명."""

    change: FileChange
    rationale: str


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────


def generate_seed_fix(
    drift: DriftItem,
    *,
    seed_md_text: str,
    client: ClaudeClient,
    seed_md_path: str = "SEED.md",
    model: str = DEFAULT_MODEL,
) -> Optional[PatchProposal]:
    """Ask Claude to update SEED.md so it matches PR reality.

    Use when ``drift.source == 'seed'`` — the PR diverged from the spec
    line. If the divergence looks intentional, Claude rewrites the line;
    if it looks like a bug, Claude declines (returns None).
    """
    system = _SYSTEM_SEED_FIX
    user = (
        f"## Drift\n"
        f"- file: {drift.source_file}\n"
        f"- line: {drift.line}\n"
        f"- requirement (verbatim): {drift.quote!r}\n"
        f"- match score: {drift.score:.2f}\n\n"
        f"## Current SEED.md\n```\n{seed_md_text}\n```"
    )
    resp = _call(client, model=model, system=system, user=user, max_tokens=DEFAULT_MAX_TOKENS)
    return _parse_proposal(resp, file_path=seed_md_path)


def generate_code_fix_proposal(
    drift: DriftItem,
    *,
    repo_context: str,
    client: ClaudeClient,
    proposals_dir: str = "docs/pr-guard-proposals",
    model: str = DEFAULT_MODEL,
) -> Optional[PatchProposal]:
    """Ask Claude to draft a proposal doc for an unmet PRD requirement.

    Returns a FileChange that adds a single markdown doc under
    ``docs/pr-guard-proposals/<slug>.md`` — NOT a code edit. Real code
    changes are deferred to a human reviewer. This is the conservative
    MVP: produce a focal point for the discussion, don't risk breaking
    the build with auto-generated code.
    """
    slug = _slug(drift)
    path = f"{proposals_dir}/{slug}.md"
    system = _SYSTEM_CODE_FIX
    user = (
        f"## Missing PRD requirement\n"
        f"- file: {drift.source_file}\n"
        f"- line: {drift.line}\n"
        f"- requirement (verbatim): {drift.quote!r}\n\n"
        f"## Relevant repo context\n```\n{repo_context}\n```\n\n"
        f"## Output path\n`{path}`"
    )
    resp = _call(client, model=model, system=system, user=user, max_tokens=DEFAULT_MAX_TOKENS)
    return _parse_proposal(resp, file_path=path)


# ──────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────


_SYSTEM_SEED_FIX = """\
You are pr-guard, a bot that proposes minimal SEED.md edits.

The user will give you ONE spec line that a PR diverged from, and the full
current SEED.md. Decide:

- If the divergence is intentional and acceptable: rewrite that line so it
  matches what the PR's code actually does. Keep the rest of SEED.md byte-
  identical. Preserve markdown structure, headings, blank lines.
- Otherwise: skip (do not return a SEED edit — pr-guard will leave the
  drift comment for a human to resolve).

OUTPUT JSON ONLY. No prose, no code fences, just the JSON object:

{"action": "update",
 "new_content": "<full updated SEED.md, verbatim>",
 "message": "<one-line conventional commit message>",
 "rationale": "<2-3 sentence explanation for the PR body>"}

OR:

{"action": "skip", "reason": "<why no edit>"}
"""


_SYSTEM_CODE_FIX = """\
You are pr-guard. The user's PR is missing a PRD-defined requirement.
Your job: produce ONE markdown discussion doc that explains what's
missing, why it matters, and a concrete proposed approach (with
pseudocode or diff fragments if helpful).

Do NOT propose to modify code directly — your output is a docs file
that a human reviewer can use as a starting point.

OUTPUT JSON ONLY:

{"action": "update",
 "new_content": "<full markdown body of the proposal doc>",
 "message": "<one-line conventional commit message>",
 "rationale": "<2-3 sentence summary for the PR body>"}

OR (if the requirement is too vague to propose anything concrete):

{"action": "skip", "reason": "<why>"}
"""


def _call(
    client: ClaudeClient,
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
) -> Any:
    """Wrap the anthropic Messages call with prompt-caching on the system block."""
    return client.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user}],
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _parse_proposal(resp: Any, *, file_path: str) -> Optional[PatchProposal]:
    text = _extract_text(resp).strip()
    if not text:
        return None
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("action") != "update":
        return None
    content = data.get("new_content")
    if not isinstance(content, str) or not content:
        return None
    message = data.get("message") or f"pr-guard: update {file_path}"
    rationale = data.get("rationale") or "Auto-generated by pr-guard."
    return PatchProposal(
        change=FileChange(path=file_path, content=content, message=message),
        rationale=rationale,
    )


def _extract_text(resp: Any) -> str:
    """Pull text out of an anthropic Messages response (SDK object or dict)."""
    content = getattr(resp, "content", None)
    if content is None and isinstance(resp, dict):
        content = resp.get("content")
    if content is None:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "\n".join(parts)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(drift: DriftItem) -> str:
    base = _SLUG_RE.sub("-", drift.quote.lower()).strip("-")[:48].rstrip("-") or "drift"
    # 안정적 충돌 방지: source_file+line 짧은 해시
    import hashlib
    digest = hashlib.sha1(
        f"{drift.source_file}:{drift.line}".encode("utf-8")
    ).hexdigest()[:6]
    return f"{base}-{digest}"
