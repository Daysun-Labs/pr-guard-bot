from __future__ import annotations

import json
import re
from typing import Any

from .models import BlockingDriftRequest, ProposalRequest

JsonObject = dict[str, Any]

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_BLOCKED_CODE_FIX_PHRASES = (
    "git push",
    "gh pr merge",
    "merge the pr",
    "auto-merge",
    "GITHUB_TOKEN",
    "HERMES_PR_GUARD_WEBHOOK_TOKEN",
)


def skip(reason: str) -> JsonObject:
    return {"action": "skip", "reason": _clean_reason(reason)}


def _clean_reason(reason: str) -> str:
    reason = " ".join(str(reason).split())
    return reason[:240] or "Skipped by PR Guard adapter."


def _clean_message(message: str) -> str:
    """Normalize harmless model formatting drift for one-line PR titles."""

    cleaned = " ".join(str(message).split())
    if len(cleaned) > 120:
        cleaned = cleaned[:119].rstrip() + "…"
    return cleaned


def parse_model_proposal(content: str) -> JsonObject:
    """Parse Hermes' final assistant message as proposal JSON.

    The prompt forbids Markdown fences, but this parser accepts a fenced JSON
    object so harmless model formatting drift still becomes deterministic JSON.
    """

    text = content.strip()
    match = _CODE_FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed JSON proposal") from exc

    if isinstance(parsed, dict) and "proposal" in parsed:
        parsed = parsed["proposal"]
    if not isinstance(parsed, dict):
        raise ValueError("malformed JSON proposal")
    return parsed


def validate_proposal(proposal: JsonObject, *, request: ProposalRequest) -> JsonObject:
    """Return a sanitized update/skip response for pr-guard-bot."""

    action = proposal.get("action")
    if action == "skip":
        return skip(str(proposal.get("reason") or "Hermes declined to propose a safe update."))
    if action != "update":
        return skip("Malformed Hermes proposal: action must be update or skip.")

    required = ("new_content", "message", "rationale")
    for field in required:
        if not isinstance(proposal.get(field), str) or not proposal[field].strip():
            return skip(f"Malformed Hermes proposal: update requires non-empty {field}.")

    new_content = proposal["new_content"].strip()
    message = _clean_message(proposal["message"])
    rationale = proposal["rationale"].strip()

    if not message:
        return skip("Malformed Hermes proposal: update requires non-empty message.")
    if len(message) > 120:
        return skip("Malformed Hermes proposal: message must be <= 120 characters.")
    if len(rationale) > 1000:
        return skip("Malformed Hermes proposal: rationale is too long.")

    if request.task == "seed_fix":
        task_result = _validate_seed_fix(new_content, request)
    elif request.task == "code_fix":
        task_result = _validate_code_fix(new_content, request)
    else:
        return skip(f"Unsupported task: {request.task}.")
    if task_result is not None:
        return task_result

    return {
        "action": "update",
        "new_content": new_content,
        "message": message,
        "rationale": rationale,
    }


def validate_blocking_decision(
    decision: JsonObject,
    *,
    request: BlockingDriftRequest,
) -> JsonObject:
    """Return sanitized blocking classifier output for pr-guard-bot."""

    entries = decision.get("blocking_indexes")
    if entries is None:
        entries = decision.get("blocking")
    if entries is None and isinstance(decision.get("classification"), dict):
        entries = decision["classification"].get("blocking")
    if not isinstance(entries, list):
        return {"blocking": []}

    blocking: list[JsonObject] = []
    seen: set[int] = set()
    item_count = len(request.advisory_drifts)
    for entry in entries:
        index: int | None = None
        reason = ""
        if isinstance(entry, int):
            index = entry
        elif isinstance(entry, dict):
            raw_index = entry.get("index")
            if isinstance(raw_index, int):
                index = raw_index
            decision_value = str(entry.get("decision", "blocking")).lower()
            if decision_value not in {"blocking", "block", "true", "yes"}:
                index = None
            reason = str(entry.get("reason") or entry.get("evidence") or "")

        if index is None or index < 0 or index >= item_count or index in seen:
            continue
        seen.add(index)
        blocking.append(
            {
                "index": index,
                "reason": _clean_reason(reason or "Classified as blocking by Hermes."),
            }
        )

    return {"blocking": blocking}


def _validate_seed_fix(new_content: str, request: ProposalRequest) -> JsonObject | None:
    if request.drift.source != "seed":
        return skip("seed_fix requires seed drift source.")
    if request.seed_md_path != "SEED.md" and not request.seed_md_path.endswith("/SEED.md"):
        return skip("seed_fix may only update SEED.md.")
    if not new_content.lstrip().startswith("#"):
        return skip("seed_fix output must be a full markdown SEED.md document.")

    original = request.seed_md_text or ""
    if original.strip():
        # Reject obviously destructive rewrites. This is intentionally coarse;
        # human review still owns semantic acceptance.
        min_chars = max(80, int(len(original) * 0.5)) if len(original) >= 160 else 1
        max_chars = max(len(original) * 4, len(original) + 5_000)
        if len(new_content) < min_chars:
            return skip("seed_fix output is too small versus the existing SEED.md.")
        if len(new_content) > max_chars:
            return skip("seed_fix output is too large versus the existing SEED.md.")
    return None


def _validate_code_fix(new_content: str, request: ProposalRequest) -> JsonObject | None:
    if request.drift.source != "prd":
        return skip("code_fix requires prd drift source.")
    output_path = request.output_path or ""
    if not (output_path.startswith("docs/pr-guard-proposals/") and output_path.endswith(".md")):
        return skip("code_fix output_path must be under docs/pr-guard-proposals/*.md.")
    if not new_content.lstrip().startswith("#"):
        return skip("code_fix output must be a markdown proposal document.")

    lowered = new_content.lower()
    for phrase in _BLOCKED_CODE_FIX_PHRASES:
        if phrase.lower() in lowered:
            return skip(
                "code_fix proposal contains unsafe direct execution or secret-bearing language."
            )
    return None
