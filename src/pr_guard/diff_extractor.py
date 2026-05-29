"""PR diff extraction module.

Parses a unified diff (as produced by `git diff` or GitHub's PR `.diff` endpoint)
into a normalized structure exposing per-file change metadata and a best-effort
list of touched symbols (function/class names) detected from hunk headers and
added/removed lines.

Pure functions only — no network. Tests feed fixture diffs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


# Common symbol patterns across Python / JS / TS / Go.
_SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*="),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"),
]


@dataclass
class FileDiff:
    path: str
    old_path: str | None
    change_type: str  # "added" | "deleted" | "modified" | "renamed"
    added_lines: int
    removed_lines: int
    symbols: list[str] = field(default_factory=list)
    hunks: list[dict[str, Any]] = field(default_factory=list)
    changed_text: str = ""
    # Added (post-image) lines and the symbols defined/touched on them. The
    # spec matcher uses these — not removed lines — as evidence that a PR
    # *implements* a requirement, so deleting code that mentions a requirement
    # never counts as satisfying it.
    added_text: str = ""
    added_symbols: list[str] = field(default_factory=list)


@dataclass
class NormalizedDiff:
    files: list[FileDiff]

    @property
    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]

    @property
    def all_symbols(self) -> list[str]:
        seen: list[str] = []
        for f in self.files:
            for s in f.symbols:
                if s not in seen:
                    seen.append(s)
        return seen

    @property
    def added_symbols(self) -> list[str]:
        """Symbols defined/touched on added lines (and hunk headers) only."""
        seen: list[str] = []
        for f in self.files:
            for s in f.added_symbols:
                if s not in seen:
                    seen.append(s)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {"files": [asdict(f) for f in self.files]}


_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(.*)$")


def _extract_symbol(line: str) -> str | None:
    for pat in _SYMBOL_PATTERNS:
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


def parse_unified_diff(diff_text: str) -> NormalizedDiff:
    """Parse a unified diff string into a NormalizedDiff structure."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    current_hunk: dict[str, Any] | None = None
    symbol_set: set[str] = set()
    added_symbol_set: set[str] = set()
    changed_lines: list[str] = []
    added_lines_text: list[str] = []

    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _DIFF_GIT_RE.match(line)
        if m:
            # finalize previous
            if current is not None:
                current.symbols = sorted(symbol_set)
                current.added_symbols = sorted(added_symbol_set)
                current.changed_text = "\n".join(changed_lines)
                current.added_text = "\n".join(added_lines_text)
                files.append(current)
            symbol_set = set()
            added_symbol_set = set()
            changed_lines = []
            added_lines_text = []
            current_hunk = None
            a_path, b_path = m.group(1), m.group(2)
            current = FileDiff(
                path=b_path,
                old_path=a_path if a_path != b_path else None,
                change_type="modified",
                added_lines=0,
                removed_lines=0,
            )
            i += 1
            # consume header lines until first hunk
            while i < len(lines) and not lines[i].startswith("@@"):
                hdr = lines[i]
                if hdr.startswith("new file mode"):
                    current.change_type = "added"
                    current.old_path = None
                elif hdr.startswith("deleted file mode"):
                    current.change_type = "deleted"
                elif hdr.startswith("rename from"):
                    current.change_type = "renamed"
                    current.old_path = hdr[len("rename from "):].strip()
                elif hdr.startswith("rename to"):
                    current.path = hdr[len("rename to "):].strip()
                elif hdr.startswith("--- ") or hdr.startswith("+++ "):
                    pass
                i += 1
            continue

        if current is None:
            i += 1
            continue

        hm = _HUNK_RE.match(line)
        if hm:
            header_tail = hm.group(1).strip()
            current_hunk = {"header": header_tail, "added": 0, "removed": 0}
            current.hunks.append(current_hunk)
            if header_tail:
                sym = _extract_symbol(header_tail)
                if sym:
                    symbol_set.add(sym)
                    added_symbol_set.add(sym)
            i += 1
            continue

        if line.startswith("+") and not line.startswith("+++"):
            changed_lines.append(line[1:])
            added_lines_text.append(line[1:])
            current.added_lines += 1
            if current_hunk is not None:
                current_hunk["added"] += 1
            sym = _extract_symbol(line[1:])
            if sym:
                symbol_set.add(sym)
                added_symbol_set.add(sym)
        elif line.startswith("-") and not line.startswith("---"):
            changed_lines.append(line[1:])
            current.removed_lines += 1
            if current_hunk is not None:
                current_hunk["removed"] += 1
            sym = _extract_symbol(line[1:])
            if sym:
                symbol_set.add(sym)
        i += 1

    if current is not None:
        current.symbols = sorted(symbol_set)
        current.added_symbols = sorted(added_symbol_set)
        current.changed_text = "\n".join(changed_lines)
        current.added_text = "\n".join(added_lines_text)
        files.append(current)

    return NormalizedDiff(files=files)


def extract_changed_files(diff_text: str) -> list[str]:
    """Return list of touched file paths (post-image)."""
    return parse_unified_diff(diff_text).file_paths


def extract_changed_symbols(diff_text: str) -> list[str]:
    """Return deduplicated list of touched symbol names across all files."""
    return parse_unified_diff(diff_text).all_symbols
