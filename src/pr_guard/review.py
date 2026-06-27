"""General PR code review via an LLM provider."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from .patcher import DEFAULT_MODEL, _FENCE_RE, _extract_text


UNKNOWN_SCORE = -1
schema_version = "pr-guard.review/v1"

_VALID_CATEGORIES = {"bug", "security", "trust_boundary", "perf", "quality"}
_VALID_SEVERITIES = {"error", "warn", "info"}


@dataclass(frozen=True)
class ReviewFinding:
    category: str
    severity: str
    file: str
    line: int
    quote: str
    suggestion: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewReport:
    findings: tuple[ReviewFinding, ...]
    score: int
    summary: str

    def to_dict(self) -> dict[str, int | str | list[dict[str, str | int]]]:
        return {
            "score": self.score,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def has_blocking_security(self) -> bool:
        return any(
            finding.category == "security" and finding.severity == "error"
            for finding in self.findings
        )


_SYSTEM_REVIEW = """\
You are pr-guard's general code reviewer for a pull request diff.

Review the PR diff for concrete bug, security, trust_boundary, perf, and quality
issues. Exclude spec/PRD/SEED drift; that is handled by another classifier.
Be conservative: report only findings grounded in the diff and repo context. If
uncertain, either lower the severity or omit the finding.

OUTPUT JSON ONLY in this exact shape:
{"score": <0-5 int>,
 "summary": "<short>",
 "findings": [
   {"category": "bug|security|trust_boundary|perf|quality",
    "severity": "error|warn|info",
    "file": "<path>",
    "line": <int>,
    "quote": "<short relevant quote>",
    "suggestion": "<specific fix or review guidance>"}
 ]}
"""


def build_review_payload(*, diff_summary: str, repo_context: str) -> dict[str, str]:
    return {
        "schema_version": schema_version,
        "diff_summary": diff_summary,
        "repo_context": repo_context,
    }


def parse_review_response(data: Any) -> ReviewReport:
    try:
        parsed = _coerce_review_mapping(data)
        if parsed is None:
            return _unknown_report("Unable to parse review response.")

        raw_findings = parsed.get("findings")
        findings = _parse_findings(raw_findings)
        score = _parse_score(parsed.get("score"))
        if score is None:
            # A provider that omits/garbles score must not be reported as a
            # concrete mediocre score (would mislead the comment/loop wiring).
            score = UNKNOWN_SCORE

        summary = parsed.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            summary = "Review response parsed without a summary."

        if score == UNKNOWN_SCORE and not isinstance(raw_findings, list):
            return _unknown_report("Review response missing score and findings.")

        return ReviewReport(findings=findings, score=score, summary=summary.strip())
    except Exception as exc:
        return _unknown_report(f"Unable to parse review response: {exc}")


def review_diff_via_client(
    client: Any,
    *,
    diff_summary: str,
    repo_context: str,
    model: str = DEFAULT_MODEL,
) -> ReviewReport:
    resp = client.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_REVIEW,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    build_review_payload(diff_summary=diff_summary, repo_context=repo_context),
                    ensure_ascii=False,
                ),
            }
        ],
    )
    return parse_review_response(resp)


def _coerce_review_mapping(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict) and any(key in data for key in ("score", "summary", "findings")):
        return data

    text = _extract_text(data).strip()
    if not text:
        if isinstance(data, str):
            text = data.strip()
        else:
            return None

    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()

    parsed = json.loads(text)
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_findings(raw_findings: Any) -> tuple[ReviewFinding, ...]:
    if not isinstance(raw_findings, list):
        return ()

    findings: list[ReviewFinding] = []
    for raw in raw_findings:
        finding = _parse_finding(raw)
        if finding is not None:
            findings.append(finding)
    return tuple(findings)


def _parse_finding(raw: Any) -> ReviewFinding | None:
    if not isinstance(raw, dict):
        return None

    category = raw.get("category")
    severity = raw.get("severity")
    file = raw.get("file")
    line = raw.get("line")
    quote = raw.get("quote")
    suggestion = raw.get("suggestion")
    if (
        not isinstance(category, str)
        or category not in _VALID_CATEGORIES
        or not isinstance(severity, str)
        or severity not in _VALID_SEVERITIES
        or not isinstance(file, str)
        or not isinstance(line, int)
        or not isinstance(quote, str)
        or not isinstance(suggestion, str)
    ):
        return None

    return ReviewFinding(
        category=category,
        severity=severity,
        file=file,
        line=line,
        quote=quote,
        suggestion=suggestion,
    )


def _parse_score(raw_score: Any) -> int | None:
    if isinstance(raw_score, bool):
        return None
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        return None
    # A negative score is the UNKNOWN_SCORE sentinel (e.g. propagated from the
    # Hermes adapter), not a real 0-5 score — surface it as unknown rather than
    # clamping it to 0 (which would make an unknown review look "terrible").
    if score < 0:
        return None
    return min(5, score)


def _unknown_report(summary: str) -> ReviewReport:
    return ReviewReport(findings=(), score=UNKNOWN_SCORE, summary=summary)
