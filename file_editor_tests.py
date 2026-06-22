"""Tests for file_editor module."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class TestIsPathEscape(unittest.TestCase):
    """Tests for _is_path_escape function."""

    def test_simple_filename(self):
        from file_editor import _is_path_escape
        self.assertFalse(_is_path_escape("/workspace", "file.py"))

    def test_dotdot_prefix(self):
        from file_editor import _is_path_escape
        self.assertTrue(_is_path_escape("/workspace", "../file.py"))

    def test_double_slash(self):
        from file_editor import _is_path_escape
        self.assertTrue(_is_path_escape("/workspace", "//etc/passwd"))

    def test_absolute_path(self):
        from file_editor import _is_path_escape
        self.assertTrue(_is_path_escape("/workspace", "/etc/passwd"))

    def test_tilde_prefix(self):
        from file_editor import _is_path_escape
        self.assertTrue(_is_path_escape("/workspace", "~/secret"))

    def test_normal_subpath(self):
        from file_editor import _is_path_escape
        self.assertFalse(_is_path_escape("/workspace", "src/file.py"))

    def test_double_dotdot(self):
        from file_editor import _is_path_escape
        self.assertTrue(_is_path_escape("/workspace", "../../file.py"))


class TestCountDiffLines(unittest.TestCase):
    """Tests for _count_diff_lines function.

    Returns (removed_count, added_count) based on lines starting with - and +.
    """

    def test_empty_diff(self):
        from file_editor import _count_diff_lines
        removed, added = _count_diff_lines("")
        self.assertEqual((removed, added), (0, 0))

    def test_no_changes(self):
        from file_editor import _count_diff_lines
        diff = "@@ -1 +1 @@\n unchanged\n"
        removed, added = _count_diff_lines(diff)
        self.assertEqual(removed, 0)
        self.assertEqual(added, 0)

    def test_removals_only(self):
        from file_editor import _count_diff_lines
        diff = "-old line1\n-old line2\n"
        removed, added = _count_diff_lines(diff)
        self.assertEqual(removed, 2)
        self.assertEqual(added, 0)

    def test_additions_only(self):
        from file_editor import _count_diff_lines
        diff = "+new line1\n+new line2\n"
        removed, added = _count_diff_lines(diff)
        self.assertEqual(removed, 0)
        self.assertEqual(added, 2)

    def test_both_changes(self):
        from file_editor import _count_diff_lines
        diff = "-old line\n+new line\n-old line2\n"
        removed, added = _count_diff_lines(diff)
        self.assertEqual(removed, 2)
        self.assertEqual(added, 1)


class TestExecuteEdit(unittest.TestCase):
    """Tests for execute_edit function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cwd = self.test_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("file_ops.write_file")
    @patch("file_ops.find_and_replace")
    @patch("file_ops.normalize_text")
    @patch("file_ops.read_file")
    def test_edit_success(self, mock_read, mock_normalize, mock_fnr, mock_write):
        from file_editor import execute_edit

        original = "def foo():\n    return 1"
        modified = "def foo():\n    return 42"
        mock_read.return_value = (original, None)
        mock_normalize.side_effect = lambda x, strict=False: x
        mock_fnr.return_value = ("", modified, 1, 2)
        mock_write.return_value = None

        act = {
            "path": "test.py",
            "find": "return 1",
            "finds": ["return 1"],
            "replace": "return 42",
            "replaces": ["return 42"],
            "remote": None,
        }

        result = execute_edit(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Successfully edited", result)

    @patch("file_ops.find_and_replace")
    @patch("file_ops.normalize_text")
    @patch("file_ops.read_file")
    def test_edit_read_error(self, mock_read, mock_normalize, mock_fnr):
        from file_editor import execute_edit

        mock_read.return_value = (None, "file not found")
        mock_normalize.side_effect = lambda x, strict=False: x

        act = {
            "path": "missing.py",
            "find": "x",
            "finds": ["x"],
            "replace": "y",
            "replaces": ["y"],
            "remote": None,
        }

        result = execute_edit(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Error reading", result)

    @patch("file_ops.find_and_replace")
    @patch("file_ops.normalize_text")
    @patch("file_ops.read_file")
    def test_edit_find_and_replace_exception(self, mock_read, mock_normalize, mock_fnr):
        from file_editor import execute_edit

        original = "def foo():\n    return 1"
        mock_read.return_value = (original, None)
        mock_normalize.side_effect = lambda x, strict=False: x
        mock_fnr.side_effect = Exception("multiple matches")

        act = {
            "path": "test.py",
            "find": "x",
            "finds": ["x"],
            "replace": "X",
            "replaces": ["X"],
            "remote": None,
        }

        result = execute_edit(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Edit failed", result)

    @patch("file_ops.write_file")
    @patch("file_ops.find_and_replace")
    @patch("file_ops.normalize_text")
    @patch("file_ops.read_file")
    def test_edit_multiple_pairs(self, mock_read, mock_normalize, mock_fnr, mock_write):
        from file_editor import execute_edit

        original = "aaa\nbbb"
        step1 = "AAA\nbbb"
        step2 = "AAA\nBBB"
        mock_read.return_value = (original, None)
        mock_normalize.side_effect = lambda x, strict=False: x
        mock_fnr.side_effect = [
            ("", step1, 1, 1),
            ("", step2, 2, 2),
        ]
        mock_write.return_value = None

        act = {
            "path": "test.py",
            "find": "aaa",
            "finds": ["aaa", "bbb"],
            "replace": "AAA",
            "replaces": ["AAA", "BBB"],
            "remote": None,
        }

        result = execute_edit(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("2 edits", result)


class TestExecuteWrite(unittest.TestCase):
    """Tests for execute_write function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.cwd = self.test_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("file_ops.write_file")
    @patch("file_ops.check_syntax")
    def test_write_creates_file(self, mock_syntax, mock_write):
        from file_editor import execute_write

        mock_syntax.return_value = (True, "")
        mock_write.return_value = None

        act = {
            "path": "test.txt",
            "content": "hello world",
            "remote": None,
        }

        result = execute_write(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Wrote", result)
        mock_write.assert_called_once()

    @patch("file_ops.write_file")
    @patch("file_ops.check_syntax")
    def test_write_multiline(self, mock_syntax, mock_write):
        from file_editor import execute_write

        mock_syntax.return_value = (True, "")
        mock_write.return_value = None

        act = {
            "path": "test.txt",
            "content": "line1\nline2\nline3",
            "remote": None,
        }

        result = execute_write(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Wrote", result)

    @patch("file_ops.write_file")
    @patch("file_ops.check_syntax")
    def test_write_with_error(self, mock_syntax, mock_write):
        from file_editor import execute_write

        mock_syntax.return_value = (True, "")
        mock_write.return_value = "access denied"

        act = {
            "path": "test.txt",
            "content": "data",
            "remote": None,
        }

        result = execute_write(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("Write failed", result)

    @patch("file_ops.check_syntax")
    def test_write_missing_path(self, mock_syntax):
        from file_editor import execute_write

        act = {
            "path": "",
            "content": "data",
            "remote": None,
        }

        result = execute_write(act, self.cwd, auto_mode=True, sandbox=False)
        self.assertIn("missing", result.lower())


class TestPathSafety(unittest.TestCase):
    """Tests for path safety in edit/write operations."""

    @patch("file_ops.write_file")
    @patch("file_ops.find_and_replace")
    @patch("file_ops.normalize_text")
    @patch("file_ops.read_file")
    def test_edit_warns_on_escape_path(self, mock_read, mock_normalize, mock_fnr, mock_write):
        from file_editor import execute_edit

        original = "root:x:0:0"
        mock_read.side_effect = [
            (None, "path_escapes"),
            (original, None),
        ]
        mock_normalize.side_effect = lambda x, strict=False: x
        mock_fnr.return_value = ("", "guest:x:100:100", 1, 1)
        mock_write.return_value = None

        act = {
            "path": "../../etc/passwd",
            "find": "root",
            "finds": ["root"],
            "replace": "guest",
            "replaces": ["guest"],
            "remote": None,
        }

        result = execute_edit(act, "/workspace", auto_mode=True, sandbox=False)
        self.assertIn("Successfully edited", result)


if __name__ == "__main__":
    unittest.main()
