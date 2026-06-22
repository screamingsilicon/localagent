"""Tests for action_parser module."""

from __future__ import annotations

import unittest
from action_parser import parse_xml_actions


def _s(a="", c=""):
    """Build a shell tag string."""
    o = chr(60) + "shell"
    if a:
        o += " " + a
    return o + chr(62) + c + chr(60) + "/shell" + chr(62)


def _w(p, c, r=None):
    """Build a write tag string."""
    x = ' remote="' + r + '"' if r else ""
    return (chr(60) + "write path=\"" + p + "\"" + x
            + chr(62) + "\n" + c + "\n" + chr(60) + "/write" + chr(62))


def _e(p, pairs, r=None):
    """Build an edit tag string."""
    x = ' remote="' + r + '"' if r else ""
    inner = ""
    for a, b in pairs:
        inner += (chr(60) + "find" + chr(62) + "\n" + a + "\n"
                  + chr(60) + "/find" + chr(62) + "\n")
        inner += (chr(60) + "replace" + chr(62) + "\n" + b + "\n"
                  + chr(60) + "/replace" + chr(62) + "\n")
    return (chr(60) + "edit path=\"" + p + "\"" + x
            + chr(62) + "\n" + inner + chr(60) + "/edit" + chr(62))


class TestParseShellActions(unittest.TestCase):

    def test_basic_shell(self):
        actions = parse_xml_actions(_s(c="echo hello"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "shell")
        self.assertEqual(actions[0]["command"], "echo hello")
        self.assertIsNone(actions[0]["remote"])
        self.assertEqual(actions[0]["timeout"], 60)

    def test_shell_with_remote(self):
        actions = parse_xml_actions(_s(a='remote="user@host"', c="ls -la"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["command"], "ls -la")
        self.assertEqual(actions[0]["remote"], "user@host")

    def test_shell_with_timeout(self):
        actions = parse_xml_actions(_s(a='timeout="120"', c="sleep 10"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["command"], "sleep 10")
        self.assertEqual(actions[0]["timeout"], 120)

    def test_shell_with_remote_and_timeout(self):
        actions = parse_xml_actions(
            _s(a='remote="root@server" timeout="30"', c="uptime"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["remote"], "root@server")
        self.assertEqual(actions[0]["timeout"], 30)

    def test_shell_multiline(self):
        actions = parse_xml_actions(_s(c="echo hello\necho world"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["command"], "echo hello\necho world")

    def test_multiple_shell(self):
        text = _s(c="echo first") + "\n" + _s(a='remote="host"', c="echo second")
        actions = parse_xml_actions(text)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["command"], "echo first")
        self.assertEqual(actions[1]["command"], "echo second")

    def test_shell_empty(self):
        actions = parse_xml_actions(_s(c=""))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["command"], "")


class TestParseWriteActions(unittest.TestCase):

    def test_basic_write(self):
        actions = parse_xml_actions(_w("test.txt", "hello world"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "write")
        self.assertEqual(actions[0]["path"], "test.txt")
        self.assertEqual(actions[0]["content"], "hello world")

    def test_write_multiline(self):
        actions = parse_xml_actions(_w("file.py", "def foo():\n    return 42"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["content"], "def foo():\n    return 42")

    def test_write_with_remote(self):
        actions = parse_xml_actions(_w("remote.txt", "content", r="user@host"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["remote"], "user@host")


class TestParseEditActions(unittest.TestCase):

    def test_basic_edit(self):
        actions = parse_xml_actions(_e("file.py", [("old code", "new code")]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "edit")
        self.assertEqual(actions[0]["path"], "file.py")
        self.assertEqual(actions[0]["find"], "old code")
        self.assertEqual(actions[0]["replace"], "new code")

    def test_edit_with_remote(self):
        actions = parse_xml_actions(_e("file.py", [("old", "new")], r="user@host"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["remote"], "user@host")

    def test_edit_multiline(self):
        actions = parse_xml_actions(
            _e("file.py", [("def foo():\n    return 1", "def foo():\n    return 42")]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["find"], "def foo():\n    return 1")

    def test_edit_multiple_pairs(self):
        actions = parse_xml_actions(_e("file.py", [("aaa", "AAA"), ("bbb", "BBB")]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["finds"], ["aaa", "bbb"])
        self.assertEqual(actions[0]["replaces"], ["AAA", "BBB"])

    def test_edit_three_pairs(self):
        actions = parse_xml_actions(
            _e("file.py", [("one", "ONE"), ("two", "TWO"), ("three", "THREE")]))
        self.assertEqual(len(actions), 1)
        self.assertEqual(len(actions[0]["finds"]), 3)


class TestMixedActions(unittest.TestCase):

    def test_shell_and_edit(self):
        text = _s(c="ls -la") + "\n" + _e("file.py", [("old", "new")])
        actions = parse_xml_actions(text)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["type"], "shell")
        self.assertEqual(actions[1]["type"], "edit")

    def test_shell_and_write(self):
        text = _s(c="echo start") + "\n" + _w("new.txt", "content")
        actions = parse_xml_actions(text)
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["type"], "shell")
        self.assertEqual(actions[1]["type"], "write")

    def test_all_three(self):
        text = (_s(c="hi") + "\n" + _e("a.py", [("x", "y")])
                + "\n" + _w("b.txt", "data"))
        actions = parse_xml_actions(text)
        self.assertEqual(len(actions), 3)


class TestEdgeCases(unittest.TestCase):

    def test_no_actions(self):
        self.assertEqual(parse_xml_actions("plain text"), [])

    def test_empty_string(self):
        self.assertEqual(parse_xml_actions(""), [])

    def test_unclosed_shell(self):
        unclosed = chr(60) + "shell" + chr(62) + "echo hello"
        self.assertEqual(len(parse_xml_actions(unclosed)), 0)


if __name__ == "__main__":
    unittest.main()
