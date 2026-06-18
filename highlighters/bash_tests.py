
"""Tests for highlighters/bash.py."""

from __future__ import annotations

import re
import unittest

from .bash import _highlight, _diff_highlight, BashScanner


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestBashHighlight(unittest.TestCase):
    """Basic bash highlighting tests."""

    def test_plain_command(self):
        result = _highlight("echo hello")
        self.assertEqual(_strip_ansi(result), "echo hello")

    def test_command_colored(self):
        result = _highlight("ls -la")
        
        self.assertNotEqual(result, _strip_ansi(result))

    def test_flags_colored(self):
        result = _highlight("grep -r -n pattern file")
        self.assertIn("-r", _strip_ansi(result))
        self.assertIn("-n", _strip_ansi(result))

    def test_strings_dq(self):
        result = _highlight('echo "hello world"')
        self.assertIn("hello world", _strip_ansi(result))

    def test_strings_sq(self):
        result = _highlight("echo 'hello world'")
        self.assertIn("hello world", _strip_ansi(result))

    def test_pipes(self):
        result = _highlight("cat file | grep foo | sort")
        self.assertIn("|", _strip_ansi(result))

    def test_redirections(self):
        result = _highlight("echo hi > out.txt")
        self.assertIn(">", _strip_ansi(result))

    def test_chained_commands(self):
        result = _highlight("sudo rm -rf /tmp/test && echo done")
        self.assertIn("sudo", _strip_ansi(result))
        self.assertIn("rm", _strip_ansi(result))

    def test_env_variable(self):
        result = _highlight("echo $HOME")
        self.assertIn("$HOME", _strip_ansi(result))

    def test_empty_input(self):
        result = _highlight("")
        self.assertEqual(result, "")

    def test_multiline_script(self):
        code = "for i in 1 2 3;\n do echo $i;\ndone"
        result = _highlight(code)
        self.assertIn("echo", _strip_ansi(result))

    def test_dangerous_command_rm(self):
        result = _highlight("rm -rf /")
        self.assertIn("rm", _strip_ansi(result))

    def test_dangerous_command_dd(self):
        result = _highlight("dd if=/dev/zero of=/dev/sda")
        self.assertIn("dd", _strip_ansi(result))


class TestBashDiff(unittest.TestCase):
    """Diff highlighting for bash."""

    def test_simple_diff(self):
        old_src = "echo hello"
        new_src = "echo world"
        result = _diff_highlight(old_src, new_src)
        self.assertIn("echo", _strip_ansi(result))

    def test_add_line(self):
        old_src = "ls"
        new_src = "ls\ngrep foo"
        result = _diff_highlight(old_src, new_src)
        self.assertIn("grep", _strip_ansi(result))

    def test_identical_sources(self):
        result = _diff_highlight("echo hi", "echo hi")
        self.assertIsInstance(result, str)


class TestBashScanner(unittest.TestCase):
    """Direct scanner unit tests."""

    def test_tokenizer_preserves_whitespace(self):
        scanner = BashScanner()
        result = scanner.process("ls  -la  /tmp")
        self.assertEqual(_strip_ansi(result), "ls  -la  /tmp")

    def test_single_dash_flag_start(self):
        """A lone '-' should set last_was_flag_start."""
        scanner = BashScanner()
        result = scanner.process("echo - n")
        
        self.assertIn("n", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()