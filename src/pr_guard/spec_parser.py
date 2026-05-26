"""PRD/SEED parser — extracts structured requirement items from a repo's PRD/SEED files.

Sub-AC 1 scope: pure-Python parser, stdlib only. Produces a list of structured
``Requirement`` objects from a repo path containing PRD.md and/or SEED.md.

Design:
- No YAML/markdown libs required (stays within current pyproject deps).
- Markdown: extracts numbered list items, bullet items, and table rows under
  sections relevant to requirements ("성공 기준", "인수 조건", "Success",
  "Acceptance", "Requirements", "DoD").
- SEED.yaml (if present): a minimal YAML reader handles the
  ``acceptance_criteria:`` and ``constraints:`` list-of-strings blocks that
  the project's own SEED.yaml uses. Anything richer is ignored — callers
  should fall back to SEED.md parsing.

Each ``Requirement`` carries enough provenance (source file, section, line)
that downstream drift classification can cite it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable


# Section headings (case-insensitive substring match) that contain
# verifiable requirement statements.
_REQUIREMENT_SECTION_HINTS = (
    "성공 기준",
    "인수 조건",
    "인수조건",
    "acceptance",
    "requirements",
    "success criteria",
    "dod",
    "비-목표",
    "non-goal",
    "제약",
    "constraints",
)


@dataclass(frozen=True)
class Requirement:
    """One verifiable requirement item extracted from PRD or SEED."""

    source: str  # "prd" | "seed"
    source_file: str  # relative path
    section: str  # nearest heading text
    kind: str  # "intent" | "constraint" | "acceptance" | "non_goal"
    text: str
    line: int  # 1-based line number in source_file

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpecBundle:
    """All requirements parsed from a repository."""

    prd_path: str | None
    seed_path: str | None
    seed_yaml_path: str | None
    requirements: list[Requirement] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prd_path": self.prd_path,
            "seed_path": self.seed_path,
            "seed_yaml_path": self.seed_yaml_path,
            "requirements": [r.to_dict() for r in self.requirements],
            "missing": list(self.missing),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_repo(repo_root: str | Path) -> SpecBundle:
    """Parse PRD.md, SEED.md, and SEED.yaml at ``repo_root`` into a SpecBundle."""
    root = Path(repo_root)
    prd = root / "PRD.md"
    seed_md = root / "SEED.md"
    seed_yaml = root / "SEED.yaml"

    bundle = SpecBundle(
        prd_path=str(prd.relative_to(root)) if prd.exists() else None,
        seed_path=str(seed_md.relative_to(root)) if seed_md.exists() else None,
        seed_yaml_path=str(seed_yaml.relative_to(root)) if seed_yaml.exists() else None,
    )

    if prd.exists():
        bundle.requirements.extend(parse_prd_markdown(prd.read_text(encoding="utf-8"), str(prd.relative_to(root))))
    else:
        bundle.missing.append("PRD.md")

    if seed_md.exists():
        bundle.requirements.extend(parse_seed_markdown(seed_md.read_text(encoding="utf-8"), str(seed_md.relative_to(root))))
    else:
        bundle.missing.append("SEED.md")

    if seed_yaml.exists():
        bundle.requirements.extend(parse_seed_yaml(seed_yaml.read_text(encoding="utf-8"), str(seed_yaml.relative_to(root))))

    return bundle


def parse_prd_markdown(text: str, source_file: str = "PRD.md") -> list[Requirement]:
    """Parse PRD markdown into Requirement items."""
    return list(_parse_markdown(text, source_file, source="prd"))


def parse_seed_markdown(text: str, source_file: str = "SEED.md") -> list[Requirement]:
    """Parse SEED markdown into Requirement items."""
    return list(_parse_markdown(text, source_file, source="seed"))


def parse_seed_yaml(text: str, source_file: str = "SEED.yaml") -> list[Requirement]:
    """Parse the ``acceptance_criteria`` and ``constraints`` lists out of SEED.yaml.

    Intentionally minimal: handles the two top-level list-of-strings keys this
    project's seed format defines. Other keys are skipped.
    """
    out: list[Requirement] = []
    lines = text.splitlines()
    current_key: str | None = None
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        # Top-level key line, e.g. "acceptance_criteria:"
        m_key = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*$", line)
        if m_key:
            current_key = m_key.group(1)
            continue
        # New top-level key with inline value resets list context.
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\s*:\s*\S", line):
            current_key = None
            continue
        if current_key in ("acceptance_criteria", "constraints"):
            m_item = re.match(r"^\s*-\s+(.*)$", line)
            if m_item:
                item = _strip_quotes(m_item.group(1).strip())
                if item:
                    out.append(
                        Requirement(
                            source="seed",
                            source_file=source_file,
                            section=current_key,
                            kind="acceptance" if current_key == "acceptance_criteria" else "constraint",
                            text=item,
                            line=i,
                        )
                    )
    return out


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}.*$")


def _parse_markdown(text: str, source_file: str, *, source: str) -> Iterable[Requirement]:
    section = ""
    section_kind = "intent"
    in_code = False
    table_header_seen = False

    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()

        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        m_h = _HEADING_RE.match(line)
        if m_h:
            section = m_h.group(2).strip()
            section_kind = _classify_section(section)
            table_header_seen = False
            continue

        if not _section_is_requirement(section):
            continue

        # Bullet
        m_b = _BULLET_RE.match(line)
        if m_b:
            txt = _clean_inline(m_b.group(1))
            if txt:
                yield Requirement(source, source_file, section, section_kind, txt, i)
            continue

        # Numbered
        m_n = _NUMBERED_RE.match(line)
        if m_n:
            txt = _clean_inline(m_n.group(1))
            if txt:
                yield Requirement(source, source_file, section, section_kind, txt, i)
            continue

        # Table rows — skip header + separator, then emit each data row.
        m_t = _TABLE_ROW_RE.match(line)
        if m_t:
            if _TABLE_SEP_RE.match(line):
                table_header_seen = True
                continue
            if not table_header_seen:
                # header row
                table_header_seen = False  # will flip on next sep
                continue
            cells = [c.strip() for c in m_t.group(1).split("|")]
            txt = " | ".join(c for c in cells if c)
            if txt:
                yield Requirement(source, source_file, section, section_kind, txt, i)


def _classify_section(section: str) -> str:
    s = section.lower()
    if "비-목표" in section or "non-goal" in s or "비목표" in section:
        return "non_goal"
    if "제약" in section or "constraint" in s:
        return "constraint"
    if "인수" in section or "acceptance" in s or "dod" in s:
        return "acceptance"
    return "intent"


def _section_is_requirement(section: str) -> bool:
    if not section:
        return False
    s = section.lower()
    return any(hint in section or hint in s for hint in _REQUIREMENT_SECTION_HINTS)


def _clean_inline(text: str) -> str:
    # Strip markdown emphasis / inline code wrappers but keep the words.
    t = text.strip()
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    return t.strip()


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s
