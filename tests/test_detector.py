from pathlib import Path

from pr_guard.detector import detect_spec_files, has_prd, has_seed


def test_empty_repo_returns_false(tmp_path: Path) -> None:
    assert has_prd(tmp_path) is False
    assert has_seed(tmp_path) is False
    assert detect_spec_files(tmp_path) == {"prd": False, "seed": False}


def test_prd_md_detected(tmp_path: Path) -> None:
    (tmp_path / "PRD.md").write_text("# PRD")
    assert has_prd(tmp_path) is True
    assert has_seed(tmp_path) is False


def test_seed_yaml_detected(tmp_path: Path) -> None:
    (tmp_path / "SEED.yaml").write_text("goal: x")
    assert has_seed(tmp_path) is True


def test_both_present(tmp_path: Path) -> None:
    (tmp_path / "PRD.md").write_text("x")
    (tmp_path / "SEED.md").write_text("y")
    assert detect_spec_files(tmp_path) == {"prd": True, "seed": True}


def test_nested_docs_path(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PRD.md").write_text("x")
    assert has_prd(tmp_path) is True


def test_directory_not_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "PRD.md").mkdir()
    assert has_prd(tmp_path) is False
