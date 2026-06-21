"""Tests for highlighters/yaml.py."""

from __future__ import annotations

import re
import unittest

from .yaml import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestYamlHighlight(unittest.TestCase):
    """Basic YAML highlighting tests."""

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_simple_key_value(self):
        result = highlight("name: Alice\n")
        plain = _strip_ansi(result)
        self.assertIn("name", plain)
        self.assertIn("Alice", plain)

    def test_plain_text_passthrough(self):
        yaml_src = "key: value\n"
        result = highlight(yaml_src)
        self.assertEqual(_strip_ansi(result), yaml_src)

    def test_nested_mapping(self):
        yaml_src = """user:
  name: Bob
  age: 30
"""
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("name", plain)
        self.assertIn("Bob", plain)
        self.assertIn("age", plain)

    def test_list_items(self):
        yaml_src = """- apple
- banana
- cherry
"""
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("apple", plain)
        self.assertIn("banana", plain)
        self.assertIn("cherry", plain)

    def test_list_inline(self):
        yaml_src = "fruits: [apple, banana, cherry]"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertEqual(plain, yaml_src)

    def test_boolean_true(self):
        yaml_src = "active: true\n"
        result = highlight(yaml_src)
        self.assertIn("true", _strip_ansi(result))
        # Should be colored
        self.assertNotEqual(result, _strip_ansi(result))

    def test_boolean_false(self):
        yaml_src = "disabled: false\n"
        result = highlight(yaml_src)
        self.assertIn("false", _strip_ansi(result))

    def test_boolean_yes_no(self):
        yaml_src = "enabled: yes\ndisabled: no\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("yes", plain)
        self.assertIn("no", plain)

    def test_boolean_on_off(self):
        yaml_src = "power: on\nsleep: off\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("on", plain)
        self.assertIn("off", plain)

    def test_null_value(self):
        yaml_src = "value: null\n"
        result = highlight(yaml_src)
        self.assertIn("null", _strip_ansi(result))

    def test_tilde_null(self):
        yaml_src = "value: ~\n"
        result = highlight(yaml_src)
        self.assertIn("~", _strip_ansi(result))

    def test_number_integer(self):
        yaml_src = "count: 42\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("42", plain)

    def test_number_float(self):
        yaml_src = "pi: 3.14159\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("3.14159", plain)

    def test_negative_number(self):
        yaml_src = "temp: -10\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("-10", plain)

    def test_double_quoted_string(self):
        yaml_src = 'name: "Alice"\n'
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)

    def test_single_quoted_string(self):
        yaml_src = "name: 'Bob'\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("Bob", plain)

    def test_comment(self):
        yaml_src = "# This is a comment\nkey: value  # inline comment\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("comment", plain)

    def test_document_separator(self):
        yaml_src = "---\nkey: value\n...\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("---", plain)
        self.assertIn("...", plain)

    def test_yaml_directive(self):
        yaml_src = "%YAML 1.1\n---\nkey: value\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("%YAML", plain)

    def test_tag_shorthand(self):
        yaml_src = "value: !!str 42\n"
        result = highlight(yaml_src)
        self.assertIn("!!str", _strip_ansi(result))

    def test_anchor_and_alias(self):
        yaml_src = """defaults: &defaults
  adapter: postgres
  host: localhost
production:
  <<: *defaults
  host: prod-db.example.com
"""
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("&defaults", plain)
        self.assertIn("*defaults", plain)

    def test_flow_mapping(self):
        yaml_src = "person: {name: Alice, age: 30}\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)

    def test_complex_yaml_document(self):
        yaml_src = """---
# Database configuration
database:
  host: localhost
  port: 5432
  name: myapp
  credentials:
    username: admin
    password: "s3cret"
  options:
    ssl: true
    timeout: 30
    retries: null

# Features list
features:
  - auth
  - logging
  - cache
"""
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("localhost", plain)
        self.assertIn("5432", plain)
        self.assertIn("admin", plain)
        self.assertIn("ssl", plain)
        self.assertIn("auth", plain)

    def test_colors_are_injected(self):
        """Ensure that highlighting actually adds ANSI codes."""
        yaml_src = "key: value\nnumber: 42\nflag: true\nnothing: null\n"
        result = highlight(yaml_src)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_whitespace_preserved(self):
        yaml_src = "  key:   value  \n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertEqual(plain, yaml_src)

    def test_unicode_values(self):
        yaml_src = "greeting: \\u3053\\u3093\\u306b\\u3061\\u306f\nemoji: \\U0001F600\n"
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("greeting", plain)

    def test_key_with_special_chars(self):
        yaml_src = '"key-with-dashes": value\n'
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("key-with-dashes", plain)

    def test_multiple_documents(self):
        yaml_src = """---
doc1: first
---
doc2: second
"""
        result = highlight(yaml_src)
        plain = _strip_ansi(result)
        self.assertIn("first", plain)
        self.assertIn("second", plain)


class TestYamlDiff(unittest.TestCase):
    """Diff highlighting for YAML."""

    def test_simple_diff(self):
        old_src = "name: Alice\n"
        new_src = "name: Bob\n"
        result = diff_highlight(old_src, new_src)
        self.assertIn("name", _strip_ansi(result))

    def test_add_key(self):
        old_src = "a: 1\n"
        new_src = "a: 1\nb: 2\n"
        result = diff_highlight(old_src, new_src)
        self.assertIn("b", _strip_ansi(result))

    def test_remove_key(self):
        old_src = "a: 1\nb: 2\n"
        new_src = "a: 1\n"
        result = diff_highlight(old_src, new_src)
        stripped = _strip_ansi(result)
        self.assertIn("-", stripped)

    def test_identical_sources(self):
        src = "key: value\n"
        result = diff_highlight(src, src)
        self.assertIsInstance(result, str)

    def test_multiline_diff(self):
        old_src = """host: localhost
port: 5432
"""
        new_src = """host: prod-db.example.com
port: 5432
"""
        result = diff_highlight(old_src, new_src)
        self.assertIn("host", _strip_ansi(result))


class TestYamlEdgeCases(unittest.TestCase):
    """Edge cases and malformed input."""

    def test_malformed_yaml_no_crash(self):
        """Malformed YAML should not crash the highlighter."""
        result = highlight("key: [\n")
        self.assertIsInstance(result, str)

    def test_tabs_in_yaml(self):
        result = highlight("key:\n\tvalue\n")
        self.assertIsInstance(result, str)

    def test_empty_keys(self):
        result = highlight(": value\n")
        self.assertIsInstance(result, str)

    def test_just_a_scalar(self):
        result = highlight("hello world\n")
        plain = _strip_ansi(result)
        self.assertIn("hello world", plain)

    def test_quoted_empty_string(self):
        result = highlight('key: ""\n')
        plain = _strip_ansi(result)
        self.assertIn('""', plain)

    def test_single_quotes_with_escape(self):
        result = highlight("key: 'it''s'\n")
        plain = _strip_ansi(result)
        self.assertIn("it", plain)

    def test_numeric_string_value(self):
        """A string that looks like a number but is quoted."""
        result = highlight('key: "42"\n')
        plain = _strip_ansi(result)
        self.assertIn("42", plain)

    def test_boolean_in_string(self):
        result = highlight('key: "true"\n')
        plain = _strip_ansi(result)
        self.assertIn("true", plain)

    def test_colon_in_value(self):
        result = highlight("time: 12:30:00\n")
        plain = _strip_ansi(result)
        self.assertIn("12:30:00", plain)

    def test_url_value(self):
        result = highlight("url: https://example.com:8080/path\n")
        plain = _strip_ansi(result)
        self.assertIn("https://example.com:8080/path", plain)


class TestYamlShowTrailing(unittest.TestCase):
    """Test trailing whitespace visualization."""

    def test_trailing_spaces_visualized(self):
        result = highlight("key: value   \n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_trailing_tabs_visualized(self):
        result = highlight("key: value\t\n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_no_trailing_no_markers(self):
        result = highlight("key: value\n", show_trailing=True)
        self.assertNotIn("\u00b7", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()
