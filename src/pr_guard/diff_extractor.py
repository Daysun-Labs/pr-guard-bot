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


# Path classification — recognises "coverage-only" PRs whose entire change set
# is regression tests and/or documentation. The spec matcher credits test files
# as code for token evidence (a ``.test.ts`` file is ``.ts`` code), so a pure
# test PR otherwise manufactures false-positive ``missing_requirement`` drift
# against any spec line that merely shares vocabulary with the new tests. At the
# PR level, though, a tests/docs-only diff introduces no product implementation:
# the implementation already landed on the base branch and this PR only adds
# coverage. ``is_coverage_only_diff`` lets the drift layer suppress unmet
# *implementation* requirements for exactly those PRs — and only those, so real
# source drift is never hidden.
_TEST_DIR_SEGMENTS = frozenset({"tests", "__tests__", "__test__"})
_TEST_BASENAME_RE = re.compile(
    r"^test_.+\.py$"            # pytest module:   test_foo.py
    r"|^.+_test\.(py|go)$"      # go/py suffix:    foo_test.go / foo_test.py
    r"|^conftest\.py$"          # pytest fixtures: conftest.py
    r"|\.(test|spec)\.[cm]?[jt]sx?$"  # JS/TS:    foo.test.ts / bar.spec.tsx / x.test.mjs
)
_DOC_DIR_SEGMENTS = frozenset({"docs", "doc"})
_DOC_EXTENSIONS = frozenset({".md", ".mdx", ".rst", ".txt"})


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


def is_test_path(path: str) -> bool:
    """True when ``path`` is a regression-test file.

    Recognises files under a ``tests``/``__tests__`` directory and the common
    JS/TS/Python/Go test-file naming conventions. Deliberately conservative:
    ambiguous product paths (e.g. ``packages/test-utils/src/index.ts``) are *not*
    treated as tests, so a source file is never misread as coverage.
    """
    p = path.replace("\\", "/").lower()
    segments = p.split("/")
    if any(seg in _TEST_DIR_SEGMENTS for seg in segments):
        return True
    base = segments[-1] if segments else p
    return bool(_TEST_BASENAME_RE.search(base))


def is_doc_path(path: str) -> bool:
    """True when ``path`` is documentation (incl. the root PRD.md/SEED.md contract)."""
    p = path.replace("\\", "/").lower()
    segments = p.split("/")
    if any(seg in _DOC_DIR_SEGMENTS for seg in segments):
        return True
    base = segments[-1] if segments else p
    return any(base.endswith(ext) for ext in _DOC_EXTENSIONS)


def is_coverage_only_diff(diff: NormalizedDiff) -> bool:
    """True when every changed file is a regression test or documentation.

    A coverage-only PR introduces no product implementation, so an unmet
    *implementation* requirement is not drift — the implementation already
    landed on the base branch and this PR only adds tests/docs against it.

    Returns ``False`` for an empty diff and for any diff that touches a
    non-test, non-doc file — product source, CI workflows (``.github/**``),
    config, lockfiles, migrations, etc. — so genuine source drift is never
    suppressed. The classification errs toward "source": anything not clearly a
    test or doc counts as implementation.
    """
    files = diff.files
    if not files:
        return False
    return all(is_test_path(f.path) or is_doc_path(f.path) for f in files)
