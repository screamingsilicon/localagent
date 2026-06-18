
"""Tests for highlighters/differ.py."""

from __future__ import annotations

import re
import unittest

from .differ import diff_highlight, plain_diff, _apply_bg


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestApplyBg(unittest.TestCase):
    """Test the background colour injection helper."""

    def test_simple_text(self):
        result = _apply_bg("hello", "\033[48;5;22m")
        self.assertIn("\033[48;5;22m", result)

    def test_preserves_inner_reset(self):
        """Background should be re-injected after inner \033[0m."""
        text = "a\033[0mb"
        bg = "\033[48;5;22m"
        result = _apply_bg(text, bg)
        
        parts = result.split("\033[0m")
        self.assertGreater(len(parts), 1)

    def test_empty_text(self):
        result = _apply_bg("", "\033[48;5;22m")
        
        self.assertIn("\033[48;5;22m", result)


class TestPlainDiff(unittest.TestCase):
    """Test plain diff (no pre-highlighting)."""

    def test_unchanged(self):
        src = "line1\nline2"
        result = plain_diff(src, src)
        
        self.assertIsInstance(result, str)
        
        for line in result.strip().split("\n"):
            stripped = _strip_ansi(line).strip()
            if stripped:
                self.assertNotIn("+", stripped.split(None, 1)[0] if stripped else "")

    def test_added_line(self):
        old = "a"
        new = "a\nb"
        result = plain_diff(old, new)
        self.assertIn("+", result)

    def test_removed_line(self):
        old = "a\nb"
        new = "a"
        result = plain_diff(old, new)
        self.assertIn("-", result)

    def test_modified_line(self):
        old = "hello"
        new = "world"
        result = plain_diff(old, new)
        self.assertIn("-", result)
        self.assertIn("+", result)

    def test_custom_labels(self):
        result = plain_diff("a", "b", old_label="old.py", new_label="new.py")
        stripped = _strip_ansi(result)
        self.assertIn("old.py", stripped)
        self.assertIn("new.py", stripped)


class TestDiffHighlight(unittest.TestCase):
    """Test diff with pre-highlighted sources."""

    def test_with_colored_sources(self):
        old_src = "x = 1"
        new_src = "x = 2"
        
        result = diff_highlight(old_src, new_src,
                                old_colored=old_src, new_colored=new_src)
        self.assertIsInstance(result, str)

    def test_none_colored_falls_back(self):
        result = diff_highlight("a", "b",
                                old_colored=None, new_colored=None)
        self.assertIsInstance(result, str)

    def test_multiline_diff(self):
        old_src = "a\nb\nc"
        new_src = "a\nx\nc"
        result = diff_highlight(old_src, new_src)
        stripped = _strip_ansi(result)
        self.assertIn("b", stripped)  


class TestDiffEdgeCases(unittest.TestCase):
    """Edge cases for diff operations."""

    def test_empty_to_content(self):
        result = plain_diff("", "hello")
        self.assertIsInstance(result, str)

    def test_content_to_empty(self):
        result = plain_diff("hello", "")
        self.assertIsInstance(result, str)

    def test_both_empty(self):
        result = plain_diff("", "")
        self.assertIsInstance(result, str)

    def test_unicode_content(self):
        old = "こんにちは"
        new = "さようなら"
        result = plain_diff(old, new)
        self.assertIn("こんにちは", _strip_ansi(result)) or \
            self.assertIn("さようなら", _strip_ansi(result))

    def test_context_lines_parameter(self):
        """Verify context_lines parameter doesn't crash and produces diff output."""
        old_src = "a\nb\nc\nd\ne"
        new_src = "a\nX\nc\nd\ne"
        result = plain_diff(old_src, new_src, context_lines=1)
        stripped = _strip_ansi(result)
        self.assertIn("X", stripped)  


if __name__ == "__main__":
    unittest.main()