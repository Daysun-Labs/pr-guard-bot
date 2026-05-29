"""Static spec/diff matching — Sub-AC 3.

Pure function that takes parsed PRD/SEED ``Requirement`` items and a
``NormalizedDiff`` and decides for each requirement whether the PR's
structural change set plausibly satisfies it.

This is intentionally a static, syntactic check — it does *not* reason
about semantics. It looks for evidence that the requirement's salient
tokens (file paths, symbol names, keywords) appear in the diff's touched
files / symbols. Downstream LLM oracles handle deeper semantic drift.

Used by the drift classifier to produce "satisfied" vs "unmet" buckets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Iterable

from .spec_parser import Requirement
from .diff_extractor import NormalizedDiff


# Tokens that carry no signal when matching requirement text to a diff.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
        "is", "are", "be", "must", "should", "will", "shall", "that", "this",
        "it", "as", "by", "from", "at",
        # Korean fillers commonly seen in PRD/SEED bullets
        "및", "또는", "그리고", "등", "수", "있다", "한다", "있어야", "해야",
        "위해", "에서", "으로", "에게",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]*|[가-힣]+")
_PATH_HINT_RE = re.compile(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+|[A-Za-z0-9_]+/[A-Za-z0-9_./-]+")
# Split a raw token into identifier-aware subwords: snake_case, kebab-case,
# dotted paths, and camelCase all break apart, while runs of Hangul stay whole.
# This is what lets "webhook" match the identifier "send_slack_webhook" without
# letting the 2-char token "pr" match "print" — matching is on whole subwords,
# not arbitrary substrings.
_SUBTOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+|[가-힣]+")

# Token-coverage evidence is credited only to *code* changes. A requirement
# describes product behaviour; editing prose (docs) or config that merely
# mentions the requirement's vocabulary is not evidence the PR implements it.
# Doc/config-only PRs (dependency bumps, workflow edits, README changes) were
# the dominant source of false-positive drift — they share words like "guard"
# or "workflow" with spec lines without touching the behaviour. Explicit file
# and symbol references are still honoured as evidence regardless of extension.
_CODE_EXTENSIONS = frozenset(
    {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
        ".go", ".rs", ".java", ".kt", ".rb", ".php", ".c", ".h", ".cc",
        ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh", ".bash", ".sql",
    }
)


def _is_code_path(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(ext) for ext in _CODE_EXTENSIONS)


@dataclass(frozen=True)
class MatchEvidence:
    """Why a requirement was judged satisfied / unmet."""

    matched_files: list[str] = field(default_factory=list)
    matched_symbols: list[str] = field(default_factory=list)
    matched_tokens: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatchResult:
    requirement: Requirement
    satisfied: bool
    score: float  # 0.0..1.0 token-coverage signal
    evidence: MatchEvidence

    def to_dict(self) -> dict:
        return {
            "requirement": self.requirement.to_dict(),
            "satisfied": self.satisfied,
            "score": self.score,
            "evidence": asdict(self.evidence),
        }


@dataclass(frozen=True)
class MatchReport:
    satisfied: list[MatchResult]
    unmet: list[MatchResult]

    def to_dict(self) -> dict:
        return {
            "satisfied": [m.to_dict() for m in self.satisfied],
            "unmet": [m.to_dict() for m in self.unmet],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_requirements(
    requirements: Iterable[Requirement],
    diff: NormalizedDiff,
    *,
    threshold: float = 0.34,
) -> MatchReport:
    """Classify each requirement as satisfied or unmet vs the diff.

    Pure function. ``threshold`` is the minimum token-coverage score (or any
    file/symbol hit) required to mark a requirement satisfied.
    """
    # Explicit path references are honoured for any touched file (the anchor
    # logic in _match_one), but token-coverage evidence is scoped to code.
    file_paths = [f.path for f in diff.files]
    code_files = [f for f in diff.files if _is_code_path(f.path)]
    # Symbol evidence comes from added lines only: a deleted ``def foo`` is not
    # evidence that this PR implements a requirement mentioning ``foo``.
    symbols = diff.added_symbols

    satisfied: list[MatchResult] = []
    unmet: list[MatchResult] = []

    added_text = "\n".join(f.added_text for f in code_files)
    # Precompute the diff's subword index once from code-change evidence only:
    # added code lines + touched symbols + code-file path components. Token
    # coverage is exact membership against this set, so a doc/config-only PR
    # contributes no token evidence and cannot manufacture drift.
    haystack_tokens = _index_tokens(added_text)
    for f in code_files:
        haystack_tokens.update(_subtokens(f.path))
    for s in symbols:
        haystack_tokens.update(_subtokens(s))

    for req in requirements:
        result = _match_one(req, file_paths, symbols, haystack_tokens, threshold)
        if result.satisfied:
            satisfied.append(result)
        else:
            unmet.append(result)

    return MatchReport(satisfied=satisfied, unmet=unmet)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _match_one(
    req: Requirement,
    file_paths: list[str],
    symbols: list[str],
    haystack_tokens: set[str],
    threshold: float,
) -> MatchResult:
    text = req.text
    text_lower = text.lower()

    # 1) Explicit path hints in the requirement text.
    matched_files: list[str] = []
    for hint in _PATH_HINT_RE.findall(text):
        h = hint.lower()
        for p in file_paths:
            if h == p.lower() or p.lower().endswith("/" + h) or h in p.lower():
                if p not in matched_files:
                    matched_files.append(p)
    # Fallback: any file path token appears in text directly
    for p in file_paths:
        if p.lower() in text_lower and p not in matched_files:
            matched_files.append(p)

    # 2) Symbol-name hits.
    matched_symbols: list[str] = []
    for s in symbols:
        if not s:
            continue
        # Word-boundary check for symbols >= 3 chars to avoid noise.
        if len(s) >= 3 and re.search(rf"\b{re.escape(s)}\b", text):
            if s not in matched_symbols:
                matched_symbols.append(s)

    # 3) Token-coverage score over the requirement's salient subwords. A subword
    #    counts only when it appears as a whole token in the diff index — never
    #    as an incidental substring — so shared vocabulary like "pr"/"ci" no
    #    longer inflates the score against unrelated files.
    tokens = _content_subtokens(text)
    matched_tokens = [tok for tok in tokens if tok in haystack_tokens]
    score = (len(matched_tokens) / len(tokens)) if tokens else 0.0

    evidence = MatchEvidence(
        matched_files=matched_files,
        matched_symbols=matched_symbols,
        matched_tokens=matched_tokens,
    )

    satisfied = bool(matched_files) or bool(matched_symbols) or score >= threshold
    return MatchResult(requirement=req, satisfied=satisfied, score=round(score, 4), evidence=evidence)


def _subtokens(raw: str) -> list[str]:
    """Split one raw token into normalized, non-trivial subwords."""
    out: list[str] = []
    for sub in _SUBTOKEN_RE.findall(raw):
        s = sub.lower()
        if len(s) < 2 or s in _STOPWORDS:
            continue
        out.append(s)
    return out


def _index_tokens(text: str) -> set[str]:
    """Build the set of salient subwords present in arbitrary diff text."""
    index: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        index.update(_subtokens(raw))
    return index


def _content_subtokens(text: str) -> list[str]:
    """Ordered, de-duplicated salient subwords of a requirement's text."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        for tok in _subtokens(raw):
            if tok in seen:
                continue
            seen.add(tok)
            out.append(tok)
    return out
