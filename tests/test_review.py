from __future__ import annotations

import json
from typing import Any

import httpx

from pr_guard.llm_provider import AnthropicProvider, HermesWebhookProvider
from pr_guard.review import (
    UNKNOWN_SCORE,
    ReviewFinding,
    ReviewReport,
    parse_review_response,
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


def _finding(
    *,
    category: str = "bug",
    severity: str = "warn",
    file: str = "src/app.py",
    line: int = 12,
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "file": file,
        "line": line,
        "quote": "return value",
        "suggestion": "Handle the missing branch.",
    }


def test_parse_review_response_accepts_direct_dict_with_findings_and_score() -> None:
    report = parse_review_response(
        {
            "score": 4,
            "summary": "One issue found.",
            "findings": [_finding(category="quality", severity="info")],
        }
    )

    assert report == ReviewReport(
        findings=(
            ReviewFinding(
                category="quality",
                severity="info",
                file="src/app.py",
                line=12,
                quote="return value",
                suggestion="Handle the missing branch.",
            ),
        ),
        score=4,
        summary="One issue found.",
    )
    assert report.to_dict() == {
        "score": 4,
        "summary": "One issue found.",
        "findings": [_finding(category="quality", severity="info")],
    }


def test_parse_review_response_accepts_anthropic_fenced_json_response() -> None:
    payload = {"score": 5, "summary": "Clean.", "findings": [_finding()]}
    report = parse_review_response(
        {"content": [{"text": f"```json\n{json.dumps(payload)}\n```"}]}
    )

    assert report.score == 5
    assert report.summary == "Clean."
    assert report.findings[0].file == "src/app.py"


def test_parse_review_response_malformed_or_empty_returns_unknown_report() -> None:
    report = parse_review_response({"content": [{"text": "not json"}]})
    empty = parse_review_response({})

    assert report.findings == ()
    assert report.score == UNKNOWN_SCORE
    assert isinstance(report.summary, str)
    assert report.summary
    assert empty.findings == ()
    assert empty.score == UNKNOWN_SCORE
    assert empty.summary


def test_parse_review_response_surfaces_non_review_provider_skip_reason() -> None:
    # A stale Hermes adapter that predates review support routes task=review
    # through its proposal path and rejects it as a malformed proposal.
    report = parse_review_response(
        {"action": "skip", "reason": "Malformed PR Guard request: Field required."}
    )

    assert report.score == UNKNOWN_SCORE
    assert report.findings == ()
    assert "Malformed PR Guard request: Field required." in report.summary
    assert "not review-aware" in report.summary


def test_parse_review_response_skip_does_not_shadow_real_review_report() -> None:
    # An "action" key alongside a real review report must not be misread as a
    # proposal-style skip; the genuine score/findings still win.
    report = parse_review_response(
        {"action": "skip", "score": 4, "summary": "Looks fine.", "findings": []}
    )

    assert report.score == 4
    assert report.summary == "Looks fine."


def test_parse_review_response_clamps_scores() -> None:
    high = parse_review_response({"score": 9, "summary": "High.", "findings": []})
    low = parse_review_response({"score": -3, "summary": "Low.", "findings": []})

    assert high.score == 5
    # A negative score is treated as UNKNOWN (sentinel), not clamped to 0.
    assert low.score == UNKNOWN_SCORE


def test_parse_review_response_drops_malformed_findings() -> None:
    report = parse_review_response(
        {
            "score": 3,
            "summary": "Mixed.",
            "findings": [
                {"category": "bug", "severity": "warn", "file": "src/app.py"},
                _finding(file="src/ok.py", line=7),
            ],
        }
    )

    assert len(report.findings) == 1
    assert report.findings[0].file == "src/ok.py"
    assert report.findings[0].line == 7


def test_parse_review_response_missing_score_with_findings_returns_unknown() -> None:
    report = parse_review_response({"summary": "no score", "findings": [_finding()]})
    assert report.score == UNKNOWN_SCORE
    assert len(report.findings) == 1


def test_review_report_has_blocking_security_true_for_security_error() -> None:
    report = ReviewReport(
        findings=(
            ReviewFinding(
                category="security",
                severity="error",
                file="src/auth.py",
                line=44,
                quote="token",
                suggestion="Validate the token before use.",
            ),
        ),
        score=2,
        summary="Security issue.",
    )

    assert report.has_blocking_security() is True


def test_review_report_has_blocking_security_false_for_warn_or_no_security() -> None:
    warn_report = ReviewReport(
        findings=(
            ReviewFinding(
                category="security",
                severity="warn",
                file="src/auth.py",
                line=44,
                quote="token",
                suggestion="Consider validating the token earlier.",
            ),
        ),
        score=3,
        summary="Warning only.",
    )
    no_security = ReviewReport(
        findings=(
            ReviewFinding(
                category="bug",
                severity="error",
                file="src/app.py",
                line=9,
                quote="None",
                suggestion="Handle None.",
            ),
        ),
        score=2,
        summary="Bug only.",
    )

    assert warn_report.has_blocking_security() is False
    assert no_security.has_blocking_security() is False


def test_anthropic_provider_review_diff_uses_client_and_parses_report() -> None:
    class FakeMessages:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def create(self, **kwargs: Any) -> dict[str, Any]:
            self.requests.append(kwargs)
            payload = {"score": 4, "summary": "Review complete.", "findings": [_finding()]}
            return {"content": [{"text": f"```json\n{json.dumps(payload)}\n```"}]}

    class FakeClient:
        def __init__(self) -> None:
            self.messages = FakeMessages()

    client = FakeClient()
    provider = AnthropicProvider("sk-ant-test", model="claude-test", client=client)

    report = provider.review_diff(diff_summary="FILE src/app.py", repo_context="context")

    assert report.score == 4
    assert report.findings[0].category == "bug"
    request = client.messages.requests[0]
    assert request["model"] == "claude-test"
    assert request["max_tokens"] == 4096
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    user_payload = json.loads(request["messages"][0]["content"])
    assert user_payload["schema_version"] == "pr-guard.review/v1"
    assert user_payload["diff_summary"] == "FILE src/app.py"
    assert user_payload["repo_context"] == "context"


def test_hermes_provider_review_diff_posts_payload_and_parses_report() -> None:
    http = CapturingHttpClient({"score": 3, "summary": "Hermes review.", "findings": [_finding()]})
    provider = HermesWebhookProvider("https://hermes.example/pr-guard", http_client=http)

    report = provider.review_diff(diff_summary="FILE src/app.py", repo_context="context")

    assert report.score == 3
    assert report.summary == "Hermes review."
    assert report.findings[0].suggestion == "Handle the missing branch."
    request_json = http.requests[0]["json"]
    assert request_json["task"] == "review"
    assert request_json["diff_summary"] == "FILE src/app.py"
    assert request_json["repo_context"] == "context"
    assert request_json["report_shape"]["score"] == "int 0-5"
