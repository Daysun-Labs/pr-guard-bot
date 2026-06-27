"""Fixture-based unit tests for diff_extractor."""
from __future__ import annotations

from pr_guard.diff_extractor import (
    extract_changed_files,
    extract_changed_symbols,
    is_coverage_only_diff,
    is_doc_path,
    is_test_path,
    parse_unified_diff,
)


MODIFY_PY_DIFF = """\
diff --git a/src/pkg/foo.py b/src/pkg/foo.py
index 1111111..2222222 100644
--- a/src/pkg/foo.py
+++ b/src/pkg/foo.py
@@ -1,5 +1,7 @@
 import os

-def old_helper():
-    return 1
+def new_helper():
+    return 2
+
+def another():
+    return 3
"""

ADD_FILE_DIFF = """\
diff --git a/src/pkg/bar.py b/src/pkg/bar.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/src/pkg/bar.py
@@ -0,0 +1,4 @@
+class Bar:
+    def method(self):
+        return 'hi'
+
"""

DELETE_FILE_DIFF = """\
diff --git a/src/pkg/gone.py b/src/pkg/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/src/pkg/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def removed():
-    pass
"""

RENAME_DIFF = """\
diff --git a/old/name.py b/new/name.py
similarity index 95%
rename from old/name.py
rename to new/name.py
index 5555555..6666666 100644
--- a/old/name.py
+++ b/new/name.py
@@ -1,3 +1,3 @@
-def x():
+def y():
     pass
"""

MULTI_LANG_DIFF = MODIFY_PY_DIFF + ADD_FILE_DIFF


def test_parse_modified_file():
    nd = parse_unified_diff(MODIFY_PY_DIFF)
    assert len(nd.files) == 1
    f = nd.files[0]
    assert f.path == "src/pkg/foo.py"
    assert f.change_type == "modified"
    assert f.added_lines == 5
    assert f.removed_lines == 2
    assert "new_helper" in f.symbols
    assert "another" in f.symbols
    assert "old_helper" in f.symbols  # removed counts too
    assert len(f.hunks) == 1


def test_parse_added_file():
    nd = parse_unified_diff(ADD_FILE_DIFF)
    f = nd.files[0]
    assert f.path == "src/pkg/bar.py"
    assert f.change_type == "added"
    assert f.old_path is None
    assert "Bar" in f.symbols
    assert "method" in f.symbols
    assert f.removed_lines == 0


def test_parse_deleted_file():
    nd = parse_unified_diff(DELETE_FILE_DIFF)
    f = nd.files[0]
    assert f.path == "src/pkg/gone.py"
    assert f.change_type == "deleted"
    assert "removed" in f.symbols
    assert f.added_lines == 0


def test_parse_renamed_file():
    nd = parse_unified_diff(RENAME_DIFF)
    f = nd.files[0]
    assert f.path == "new/name.py"
    assert f.old_path == "old/name.py"
    assert f.change_type == "renamed"


def test_extract_changed_files_multi():
    paths = extract_changed_files(MULTI_LANG_DIFF)
    assert paths == ["src/pkg/foo.py", "src/pkg/bar.py"]


def test_extract_changed_symbols_dedup():
    syms = extract_changed_symbols(MULTI_LANG_DIFF)
    assert "Bar" in syms
    assert "new_helper" in syms
    # ordering preserved + unique
    assert len(syms) == len(set(syms))


def test_empty_diff_yields_empty_structure():
    nd = parse_unified_diff("")
    assert nd.files == []
    assert nd.file_paths == []
    assert nd.all_symbols == []


def test_to_dict_serializable():
    nd = parse_unified_diff(ADD_FILE_DIFF)
    d = nd.to_dict()
    assert d["files"][0]["path"] == "src/pkg/bar.py"
    assert d["files"][0]["change_type"] == "added"


def test_added_text_excludes_removed_lines():
    nd = parse_unified_diff(MODIFY_PY_DIFF)
    added = nd.files[0].added_text
    assert "new_helper" in added
    assert "another" in added
    # The removed definition must not appear as added evidence.
    assert "old_helper" not in added
    # changed_text still carries both sides for backward compatibility.
    assert "old_helper" in nd.files[0].changed_text


def test_added_symbols_excludes_deleted_symbols():
    nd = parse_unified_diff(MODIFY_PY_DIFF)
    assert "new_helper" in nd.added_symbols
    assert "another" in nd.added_symbols
    assert "old_helper" not in nd.added_symbols
    # all_symbols still tracks the deleted symbol.
    assert "old_helper" in nd.all_symbols


# ---------------------------------------------------------------------------
# Coverage-only scope classification (tests/docs vs source)
# ---------------------------------------------------------------------------

TESTS_ONLY_DIFF = """\
diff --git a/tests/web-minimal-surface.test.ts b/tests/web-minimal-surface.test.ts
new file mode 100644
--- /dev/null
+++ b/tests/web-minimal-surface.test.ts
@@ -0,0 +1,3 @@
+test("landing renders", () => {
+  expect(true).toBe(true);
+});
"""

DOCS_ONLY_DIFF = """\
diff --git a/PRD.md b/PRD.md
index 1111111..2222222 100644
--- a/PRD.md
+++ b/PRD.md
@@ -1,1 +1,2 @@
 # PRD
+추가 설명 한 줄.
"""

WORKFLOW_DIFF = """\
diff --git a/.github/workflows/pr-guard.yml b/.github/workflows/pr-guard.yml
index 1111111..2222222 100644
--- a/.github/workflows/pr-guard.yml
+++ b/.github/workflows/pr-guard.yml
@@ -1,1 +1,2 @@
 name: PR Guard
+# tweak
"""


def test_is_test_path_recognizes_common_patterns():
    assert is_test_path("tests/web-minimal-surface.test.ts")
    assert is_test_path("packages/brain/__tests__/recall.spec.tsx")
    assert is_test_path("tests/extract-facts.test.ts")
    assert is_test_path("test_foo.py")
    assert is_test_path("pkg/foo_test.go")
    assert is_test_path("conftest.py")


def test_is_test_path_does_not_misclassify_source():
    # 'test-utils' is product code, not a tests directory.
    assert not is_test_path("packages/test-utils/src/index.ts")
    assert not is_test_path("src/pkg/widget.py")
    assert not is_test_path(".github/workflows/pr-guard.yml")


def test_is_doc_path_recognizes_docs_and_contract():
    assert is_doc_path("PRD.md")
    assert is_doc_path("SEED.md")
    assert is_doc_path("docs/pr-guard.md")
    assert is_doc_path("notes/decision.rst")


def test_is_doc_path_excludes_source_and_config():
    assert not is_doc_path("src/pkg/widget.py")
    assert not is_doc_path(".github/workflows/pr-guard.yml")
    assert not is_doc_path("package.json")


def test_is_coverage_only_diff_true_for_tests_and_docs():
    assert is_coverage_only_diff(parse_unified_diff(TESTS_ONLY_DIFF))
    assert is_coverage_only_diff(parse_unified_diff(DOCS_ONLY_DIFF))
    assert is_coverage_only_diff(parse_unified_diff(TESTS_ONLY_DIFF + DOCS_ONLY_DIFF))


def test_is_coverage_only_diff_false_for_source_workflow_mixed_and_empty():
    assert not is_coverage_only_diff(parse_unified_diff(""))
    assert not is_coverage_only_diff(parse_unified_diff(ADD_FILE_DIFF))  # src/pkg/bar.py
    assert not is_coverage_only_diff(parse_unified_diff(WORKFLOW_DIFF))  # CI is source
    # A mix of tests and source is NOT coverage-only — real drift must surface.
    assert not is_coverage_only_diff(parse_unified_diff(TESTS_ONLY_DIFF + ADD_FILE_DIFF))
