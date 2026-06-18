
"""Tests for highlighters/python.py."""

from __future__ import annotations

import re
import unittest

from .python import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestPythonHighlight(unittest.TestCase):
    """Basic highlighting tests — verify colour codes are injected."""

    def test_plain_text_passthrough(self):
        result = highlight("x = 1")
        self.assertEqual(_strip_ansi(result), "x = 1")

    def test_keyword_colored(self):
        result = highlight("def foo():\n    pass")
        
        self.assertNotEqual(result, _strip_ansi(result))

    def test_string_colored(self):
        result = highlight('x = "hello"')
        self.assertNotEqual(result, _strip_ansi(result))

    def test_number_colored(self):
        result = highlight("x = 42")
        self.assertNotEqual(result, _strip_ansi(result))

    def test_comment_colored(self):
        result = highlight("# this is a comment")
        self.assertNotEqual(result, _strip_ansi(result))

    def test_multiline_string(self):
        code = '''"""docstring"""\ndef f(): pass'''
        result = highlight(code)
        self.assertIn("docstring", _strip_ansi(result))

    def test_fstring(self):
        result = highlight('f"hello {name}"')
        self.assertIn("hello", _strip_ansi(result))

    def test_class_definition(self):
        code = "class MyClass:\n    pass"
        result = highlight(code)
        self.assertIn("MyClass", _strip_ansi(result))

    def test_decorator(self):
        code = "@property\ndef name(self):\n    return self._name"
        result = highlight(code)
        self.assertIn("@property", _strip_ansi(result))

    def test_imports(self):
        code = "import os\nfrom sys import argv"
        result = highlight(code)
        self.assertIn("import", _strip_ansi(result))

    def test_token_error_graceful(self):
        """Malformed Python should not crash."""
        result = highlight("def f(:\n    pass")
        self.assertIsInstance(result, str)

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_dangerous_builtins_eval(self):
        code = "eval(some_expr)"
        result = highlight(code)
        
        self.assertIn("eval", _strip_ansi(result))


class TestPythonDiff(unittest.TestCase):
    """Diff highlighting tests."""

    def test_simple_diff(self):
        old_src = "x = 1\ny = 2"
        new_src = "x = 10\ny = 2"
        result = diff_highlight(old_src, new_src)
        self.assertIn("x =", _strip_ansi(result))

    def test_add_line(self):
        old_src = "a = 1"
        new_src = "a = 1\nb = 2"
        result = diff_highlight(old_src, new_src)
        self.assertIn("b = 2", _strip_ansi(result))

    def test_delete_line(self):
        old_src = "a = 1\nb = 2"
        new_src = "a = 1"
        result = diff_highlight(old_src, new_src)
        
        stripped = _strip_ansi(result)
        self.assertIn("-", stripped)

    def test_identical_sources(self):
        src = "x = 1"
        result = diff_highlight(src, src)
        
        self.assertIsInstance(result, str)


class TestCtxState(unittest.TestCase):
    """Test internal context tracking edge cases."""

    def test_annotation_tracking(self):
        code = "def foo(x: int) -> str:\n    return str(x)"
        result = highlight(code)
        self.assertIn("int", _strip_ansi(result))
        self.assertIn("str", _strip_ansi(result))

    def test_nested_parens_in_annotation(self):
        code = "def foo(x: dict[str, list[int]]) -> None:\n    pass"
        result = highlight(code)
        self.assertIn("dict", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()