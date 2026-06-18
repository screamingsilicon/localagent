
"""Tests for highlighters/html.py."""

from __future__ import annotations

import re
import unittest

from .html import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestHtmlHighlight(unittest.TestCase):
    """Basic HTML highlighting tests."""

    def test_plain_element(self):
        result = highlight("<div>hello</div>")
        self.assertEqual(_strip_ansi(result), "<div>hello</div>")

    def test_tags_colored(self):
        result = highlight("<p>text</p>")
        self.assertNotEqual(result, _strip_ansi(result))

    def test_void_element(self):
        result = highlight("<br/>")
        self.assertIn("<br", _strip_ansi(result))

    def test_attributes(self):
        result = highlight('<a href="https://example.com">link</a>')
        plain = _strip_ansi(result)
        self.assertIn("href", plain)
        self.assertIn("example.com", plain)

    def test_doctype(self):
        result = highlight("<!DOCTYPE html>")
        self.assertIn("DOCTYPE", _strip_ansi(result))

    def test_comment(self):
        result = highlight("<!-- comment -->")
        self.assertIn("comment", _strip_ansi(result))

    def test_entity(self):
        result = highlight("&amp; &lt; &gt;")
        self.assertIn("&amp;", _strip_ansi(result))

    def test_script_tag_with_js(self):
        code = "<script>\nvar x = 1;\n</script>"
        result = highlight(code)
        self.assertIn("var", _strip_ansi(result))

    def test_style_tag(self):
        code = "<style>\nbody { color: red; }\n</style>"
        result = highlight(code)
        self.assertIn("color", _strip_ansi(result))

    def test_nested_elements(self):
        code = "<div><p><span>nested</span></p></div>"
        result = highlight(code)
        self.assertIn("nested", _strip_ansi(result))

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_multiline_element(self):
        code = "<div\n  class=\"container\"\n  id=\"main\">\n</div>"
        result = highlight(code)
        self.assertIn("container", _strip_ansi(result))


class TestHtmlDiff(unittest.TestCase):
    """Diff highlighting for HTML."""

    def test_simple_diff(self):
        old_src = "<p>hello</p>"
        new_src = "<p>world</p>"
        result = diff_highlight(old_src, new_src)
        self.assertIn("<p>", _strip_ansi(result))

    def test_add_element(self):
        old_src = "<div></div>"
        new_src = "<div><p>new</p></div>"
        result = diff_highlight(old_src, new_src)
        self.assertIn("new", _strip_ansi(result))

    def test_identical_sources(self):
        result = diff_highlight("<p>x</p>", "<p>x</p>")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()