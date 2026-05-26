"""PRD/SEED 파일 존재 여부 detector.

리포 루트에서 PRD/SEED 명세 파일을 탐색하여 존재 여부를 boolean으로 반환한다.
"""
from __future__ import annotations

from pathlib import Path

PRD_CANDIDATES = ("PRD.md", "prd.md", "docs/PRD.md")
SEED_CANDIDATES = ("SEED.md", "seed.md", "SEED.yaml", "seed.yaml", "docs/SEED.md")


def _exists_any(root: Path, candidates: tuple[str, ...]) -> bool:
    for rel in candidates:
        if (root / rel).is_file():
            return True
    return False


def has_prd(repo_root: str | Path) -> bool:
    """Return True if any known PRD file exists at repo_root."""
    return _exists_any(Path(repo_root), PRD_CANDIDATES)


def has_seed(repo_root: str | Path) -> bool:
    """Return True if any known SEED file exists at repo_root."""
    return _exists_any(Path(repo_root), SEED_CANDIDATES)


def detect_spec_files(repo_root: str | Path) -> dict[str, bool]:
    """Return presence map for PRD and SEED files at the given repo root."""
    root = Path(repo_root)
    return {"prd": has_prd(root), "seed": has_seed(root)}
