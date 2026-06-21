"""Tests for highlighters/json.py."""

from __future__ import annotations

import re
import unittest

from .json import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestJsonHighlight(unittest.TestCase):
    """Basic JSON highlighting tests."""

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_plain_object_passthrough(self):
        result = highlight('{"key": "value"}')
        self.assertEqual(_strip_ansi(result), '{"key": "value"}')

    def test_simple_key_value(self):
        result = highlight('{"name": "Alice"}')
        plain = _strip_ansi(result)
        self.assertIn("name", plain)
        self.assertIn("Alice", plain)

    def test_nested_object(self):
        json_str = '{"user": {"name": "Bob", "age": 30}}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_array_of_strings(self):
        json_str = '["apple", "banana", "cherry"]'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("apple", plain)
        self.assertIn("banana", plain)

    def test_array_of_numbers(self):
        json_str = '[1, 2, 3, 42]'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_boolean_true(self):
        json_str = '{"active": true}'
        result = highlight(json_str)
        self.assertIn("true", _strip_ansi(result))
        # Should be colored (not equal to plain text)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_boolean_false(self):
        json_str = '{"disabled": false}'
        result = highlight(json_str)
        self.assertIn("false", _strip_ansi(result))

    def test_null_value(self):
        json_str = '{"value": null}'
        result = highlight(json_str)
        self.assertIn("null", _strip_ansi(result))

    def test_negative_number(self):
        json_str = '{"temp": -42}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("-42", plain)

    def test_float_number(self):
        json_str = '{"pi": 3.14159}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("3.14159", plain)

    def test_scientific_notation(self):
        json_str = '{"avogadro": 6.022e23}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("6.022e23", plain)

    def test_scientific_notation_negative_exp(self):
        json_str = '{"small": 1.5e-10}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("1.5e-10", plain)

    def test_empty_string(self):
        json_str = '{"empty": ""}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_escaped_characters_in_string(self):
        json_str = '{"msg": "hello\\nworld\\t!"}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("hello", plain)
        self.assertIn("world", plain)

    def test_unicode_in_string(self):
        json_str = '{"greeting": "\\u3053\\u3093\\u306b\\u3061\\u306f"}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("\\u3053", plain)

    def test_multiline_json(self):
        json_str = """{
  "name": "Alice",
  "age": 30,
  "active": true
}"""
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)
        self.assertIn("30", plain)
        self.assertIn("true", plain)

    def test_complex_nested_json(self):
        json_str = """{
  "users": [
    {"name": "Alice", "roles": ["admin", "user"]},
    {"name": "Bob", "roles": ["user"]}
  ],
  "meta": {
    "count": 2,
    "version": null
  }
}"""
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)
        self.assertIn("admin", plain)
        self.assertIn("Bob", plain)

    def test_deeply_nested(self):
        json_str = '{"a": {"b": {"c": {"d": 1}}}}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_mixed_types_in_array(self):
        json_str = '[1, "two", true, null, 3.14]'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_object_with_multiple_keys(self):
        json_str = '{"a": 1, "b": 2, "c": 3}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_zero_value(self):
        json_str = '{"zero": 0}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("0", plain)

    def test_negative_float(self):
        json_str = '{"val": -3.14}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("-3.14", plain)

    def test_colors_are_injected(self):
        """Ensure that highlighting actually adds ANSI codes."""
        json_str = '{"key": "value", "num": 42, "flag": true, "nada": null}'
        result = highlight(json_str)
        # Result should contain ANSI escape codes
        self.assertNotEqual(result, _strip_ansi(result))

    def test_whitespace_preserved(self):
        json_str = '  {  "key"  :  "value"  }  '
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertEqual(plain, json_str)

    def test_string_with_colons(self):
        json_str = '{"url": "https://example.com:8080/path"}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("https://example.com:8080/path", plain)

    def test_string_with_quotes_inside(self):
        json_str = '{"msg": "He said \\"hello\\""}'
        result = highlight(json_str)
        plain = _strip_ansi(result)
        self.assertIn("hello", plain)


class TestJsonDiff(unittest.TestCase):
    """Diff highlighting for JSON."""

    def test_simple_diff(self):
        old_src = '{"name": "Alice"}'
        new_src = '{"name": "Bob"}'
        result = diff_highlight(old_src, new_src)
        self.assertIn("name", _strip_ansi(result))

    def test_add_key(self):
        old_src = '{"a": 1}'
        new_src = '{"a": 1, "b": 2}'
        result = diff_highlight(old_src, new_src)
        self.assertIn("b", _strip_ansi(result))

    def test_remove_key(self):
        old_src = '{"a": 1, "b": 2}'
        new_src = '{"a": 1}'
        result = diff_highlight(old_src, new_src)
        stripped = _strip_ansi(result)
        self.assertIn("-", stripped)

    def test_identical_sources(self):
        src = '{"key": "value"}'
        result = diff_highlight(src, src)
        self.assertIsInstance(result, str)

    def test_multiline_diff(self):
        old_src = """{
  "name": "Alice",
  "age": 30
}"""
        new_src = """{
  "name": "Alice",
  "age": 31
}"""
        result = diff_highlight(old_src, new_src)
        self.assertIn("age", _strip_ansi(result))


class TestJsonEdgeCases(unittest.TestCase):
    """Edge cases and malformed input."""

    def test_malformed_json_no_crash(self):
        """Malformed JSON should not crash the highlighter."""
        result = highlight('{"key": }')
        self.assertIsInstance(result, str)

    def test_trailing_comma(self):
        result = highlight('{"a": 1,}')
        self.assertIsInstance(result, str)

    def test_single_quotes_not_json(self):
        """Single quotes are not valid JSON but should not crash."""
        result = highlight("{'key': 'value'}")
        self.assertIsInstance(result, str)

    def test_unquoted_keys(self):
        result = highlight('{key: "value"}')
        self.assertIsInstance(result, str)

    def test_just_a_number(self):
        result = highlight('42')
        plain = _strip_ansi(result)
        self.assertIn("42", plain)

    def test_just_a_string(self):
        result = highlight('"hello"')
        plain = _strip_ansi(result)
        self.assertIn("hello", plain)

    def test_just_true(self):
        result = highlight('true')
        plain = _strip_ansi(result)
        self.assertIn("true", plain)

    def test_just_null(self):
        result = highlight('null')
        plain = _strip_ansi(result)
        self.assertIn("null", plain)

    def test_empty_object(self):
        result = highlight('{}')
        plain = _strip_ansi(result)
        self.assertEqual(plain, '{}')

    def test_empty_array(self):
        result = highlight('[]')
        plain = _strip_ansi(result)
        self.assertEqual(plain, '[]')

    def test_nested_empty(self):
        result = highlight('{"a": {}, "b": []}')
        plain = _strip_ansi(result)
        self.assertEqual(plain, '{"a": {}, "b": []}')


class TestJsonShowTrailing(unittest.TestCase):
    """Test trailing whitespace visualization."""

    def test_trailing_spaces_visualized(self):
        result = highlight('  {"key": "value"}   ', show_trailing=True)
        # Should contain the visual markers for trailing spaces (red color code)
        self.assertIn("\033[1;31m", result)

    def test_no_trailing_no_markers(self):
        result = highlight('{"key": "value"}', show_trailing=True)
        # No trailing whitespace, so no trailing markers
        self.assertNotIn("\u00b7", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()
