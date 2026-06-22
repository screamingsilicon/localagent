"""Tests for shell_executor module — truncation and execution."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from shell_executor import (
    truncate_output,
    SHELL_MAX_LINES,
    SHELL_MAX_BYTES,
)


class TestNoTruncation(unittest.TestCase):
    """Output that fits within both limits passes through unchanged."""

    def test_short_output(self):
        text = "hello\nworld\n"
        result, truncated, tmp = truncate_output(text)
        self.assertFalse(truncated)
        self.assertIsNone(tmp)
        self.assertEqual(result, text)

    def test_exactly_at_line_limit(self):
        lines = "\n".join(f"line {i}" for i in range(1000)) + "\n"
        result, truncated, tmp = truncate_output(lines)
        self.assertFalse(truncated)
        self.assertIsNone(tmp)

    def test_exactly_at_byte_limit(self):
        text = "x" * (64 * 1024 - 1) + "\n"
        result, truncated, tmp = truncate_output(text)
        self.assertFalse(truncated)
        self.assertIsNone(tmp)

    def test_empty_output(self):
        result, truncated, tmp = truncate_output("")
        self.assertFalse(truncated)
        self.assertIsNone(tmp)
        self.assertEqual(result, "")


class TestLineLimitTruncation(unittest.TestCase):
    """Output exceeding line limit keeps tail."""

    def test_exceeds_lines_keeps_tail(self):
        lines = "\n".join(f"line {i}" for i in range(1500)) + "\n"
        result, truncated, tmp = truncate_output(lines)

        self.assertTrue(truncated)
        self.assertIsNotNone(tmp)
        self.assertTrue(os.path.exists(tmp))

        self.assertIn("Showing lines 501-1500 of 1500", result)
        self.assertIn("Full output:", result)

        full_content = Path(tmp).read_text()
        self.assertEqual(full_content, lines)

    def test_keeps_tail_not_head(self):
        lines = "\n".join(f"line {i}" for i in range(2000)) + "\n"
        result, truncated, tmp = truncate_output(lines)

        self.assertTrue(truncated)
        self.assertIn("line 1999", result)
        self.assertNotIn("line 0", result)

    def test_many_lines(self):
        lines = "\n".join(f"line {i}" for i in range(10000)) + "\n"
        result, truncated, tmp = truncate_output(lines)

        self.assertTrue(truncated)
        self.assertIn("Showing lines 9001-10000 of 10000", result)


class TestByteLimitTruncation(unittest.TestCase):
    """Wide output exceeding byte limit is truncated."""

    def test_single_huge_line(self):
        text = "x" * (100 * 1024) + "\n"
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated)
        self.assertIsNotNone(tmp)
        self.assertTrue(os.path.exists(tmp))
        self.assertTrue("bytes" in result.lower() or "truncated" in result.lower())

    def test_wide_lines_few_count(self):
        text = "\n".join("x" * (10 * 1024) for _ in range(10)) + "\n"
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated)
        self.assertTrue("truncated" in result.lower() or "bytes" in result.lower())

    def test_json_like_output(self):
        entries = ",".join(f'{{"id": {i}, "name": "item_"}}' for i in range(10000))
        text = '{"data": [' + entries + ']}\n'
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated, f"Expected truncation for {len(text.encode('utf-8'))} bytes")
        self.assertIsNotNone(tmp)


class TestBothLimits(unittest.TestCase):
    """Output exceeding both line AND byte limits."""

    def test_both_limits_exceeded(self):
        text = "\n".join("x" * 100 for _ in range(2000)) + "\n"
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated)
        self.assertIn("Showing lines", result)

    def test_bytes_exceeded_first(self):
        text = "\n".join("x" * 2048 for _ in range(100)) + "\n"
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated)
        self.assertIn("bytes", result.lower())


class TestCustomLimits(unittest.TestCase):
    """Custom max_lines and max_bytes parameters."""

    def test_custom_line_limit(self):
        text = "\n".join(f"line {i}" for i in range(100)) + "\n"
        result, truncated, tmp = truncate_output(text, max_lines=50)

        self.assertTrue(truncated)
        self.assertIn("Showing lines 51-100 of 100", result)

    def test_custom_byte_limit(self):
        text = "x" * 1000 + "\n"
        result, truncated, tmp = truncate_output(text, max_bytes=500)

        self.assertTrue(truncated)


class TestEdgeCases(unittest.TestCase):
    """Edge cases: unicode, mixed endings, no trailing newline."""

    def test_unicode_content(self):
        text = "\n".join("😀" * 100 for _ in range(50)) + "\n"
        result, truncated, tmp = truncate_output(text)
        self.assertIsInstance(result, str)

    def test_mixed_line_endings(self):
        text = "line1\r\nline2\nline3\r\n"
        result, truncated, tmp = truncate_output(text)
        self.assertIsInstance(result, str)

    def test_only_newlines(self):
        text = "\n" * 2000
        result, truncated, tmp = truncate_output(text)
        self.assertTrue(truncated)
        self.assertIsInstance(result, str)

    def test_no_trailing_newline(self):
        text = "\n".join(f"line {i}" for i in range(1500))
        result, truncated, tmp = truncate_output(text)
        self.assertTrue(truncated)
        self.assertIn("line 1499", result)

    def test_temp_file_readable(self):
        original = "\n".join(f"line {i}" for i in range(2000)) + "\n"
        result, truncated, tmp = truncate_output(original)

        self.assertTrue(truncated)
        self.assertIsNotNone(tmp)
        full_content = Path(tmp).read_text(encoding="utf-8")
        self.assertEqual(full_content, original)

    def test_preserves_special_chars(self):
        text = "hello $WORLD\n`cmd`\npath/to/file\n100%\n"
        result, truncated, tmp = truncate_output(text)

        self.assertFalse(truncated)
        self.assertIn("$WORLD", result)
        self.assertIn("`cmd`", result)


class TestConstants(unittest.TestCase):
    """Constants have reasonable default values."""

    def test_max_lines(self):
        self.assertEqual(SHELL_MAX_LINES, 1000)

    def test_max_bytes(self):
        self.assertEqual(SHELL_MAX_BYTES, 64 * 1024)


class TestResultFormat(unittest.TestCase):
    """Truncated result has proper format for LLM consumption."""

    def test_format_has_metadata(self):
        text = "\n".join(f"line {i}" for i in range(1500)) + "\n"
        result, truncated, tmp = truncate_output(text)

        self.assertTrue(truncated)
        self.assertTrue(result.startswith("...\n"))
        self.assertIn("[", result)
        self.assertIn("]", result)


class TestShellExecution(unittest.TestCase):
    """Integration tests for execute_shell truncation."""

    def test_truncation_shows_line_range(self):
        from shell_executor import execute_shell

        cmd = "for i in $(seq 1 1500); do echo \"line $i content here\"; done"
        result = execute_shell(
            {"command": cmd},
            auto_mode=True,
            cwd="/workspace",
            sandbox=False,
            sudo_cache=None,
            log_tool_call=None,
        )

        self.assertIn("Showing lines", result)

    def test_no_truncation_under_threshold(self):
        from shell_executor import execute_shell

        result = execute_shell(
            {"command": "echo hello; echo world"},
            auto_mode=True,
            cwd="/workspace",
            sandbox=False,
            sudo_cache=None,
            log_tool_call=None,
        )
        self.assertNotIn("Showing lines", result)
        self.assertIn("hello", result)
        self.assertIn("world", result)


if __name__ == "__main__":
    unittest.main()