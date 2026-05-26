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
    file_paths = [f.path for f in diff.files]
    file_path_set = {p.lower() for p in file_paths}
    symbols = diff.all_symbols
    symbol_set = {s.lower() for s in symbols}

    satisfied: list[MatchResult] = []
    unmet: list[MatchResult] = []

    for req in requirements:
        result = _match_one(req, file_paths, file_path_set, symbols, symbol_set, threshold)
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
    file_path_set: set[str],
    symbols: list[str],
    symbol_set: set[str],
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

    # 3) Token-coverage score across remaining content tokens.
    tokens = _content_tokens(text)
    matched_tokens: list[str] = []
    haystack = " ".join(file_paths + symbols).lower()
    for tok in tokens:
        if tok in haystack:
            matched_tokens.append(tok)
    score = (len(matched_tokens) / len(tokens)) if tokens else 0.0

    evidence = MatchEvidence(
        matched_files=matched_files,
        matched_symbols=matched_symbols,
        matched_tokens=matched_tokens,
    )

    satisfied = bool(matched_files) or bool(matched_symbols) or score >= threshold
    return MatchResult(requirement=req, satisfied=satisfied, score=round(score, 4), evidence=evidence)


def _content_tokens(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        tok = raw.strip(".-_/").lower()
        if not tok or len(tok) < 2:
            continue
        if tok in _STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out
