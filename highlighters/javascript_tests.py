"""Tests for highlighters/javascript.py."""

from __future__ import annotations

import re
import unittest

from .javascript import highlight, diff_highlight


def _strip_ansi(s: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", s)


class TestJsHighlight(unittest.TestCase):
    """Basic JavaScript highlighting tests."""

    def test_empty_input(self):
        result = highlight("")
        self.assertEqual(result, "")

    def test_plain_text_passthrough(self):
        js = "const x = 42;\n"
        result = highlight(js)
        self.assertEqual(_strip_ansi(result), js)

    def test_const_declaration(self):
        js = 'const name = "Alice";'
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("name", plain)
        self.assertIn("Alice", plain)

    def test_let_declaration(self):
        js = "let count = 0;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_var_declaration(self):
        js = "var oldStyle = true;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("oldStyle", plain)

    def test_function_declaration(self):
        js = "function greet(name) {\n  return `Hello, ${name}!`;\n}"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("greet", plain)

    def test_arrow_function(self):
        js = "const add = (a, b) => a + b;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_class_declaration(self):
        js = """class User {
  constructor(name) { this.name = name; }
  greet() { return `Hi, ${this.name}`; }
}"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("User", plain)
        self.assertIn("constructor", plain)

    def test_if_else(self):
        js = """if (x > 0) {
  console.log("positive");
} else {
  console.log("non-positive");
}"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("positive", plain)

    def test_for_loop(self):
        js = "for (let i = 0; i < arr.length; i++) { sum += arr[i]; }"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_while_loop(self):
        js = "while (condition) { doSomething(); }"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_async_await(self):
        js = """async function fetchData() {
  const response = await fetch('/api/data');
  const data = await response.json();
  return data;
}"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("fetchData", plain)

    def test_try_catch(self):
        js = """try {
  riskyOperation();
} catch (error) {
  console.error(error);
} finally {
  cleanup();
}"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("riskyOperation", plain)

    def test_double_quoted_string(self):
        js = 'const msg = "Hello, world!";'
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Hello, world!", plain)

    def test_single_quoted_string(self):
        js = "const msg = 'Hello, world!';"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Hello, world!", plain)

    def test_template_literal(self):
        js = "const greeting = `Hello, ${name}!`;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Hello", plain)

    def test_escaped_string(self):
        js = r'const path = "C:\\Users\\test";'
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Users", plain)

    def test_number_integer(self):
        js = "const count = 42;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("42", plain)

    def test_number_float(self):
        js = "const ratio = 0.618;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("0.618", plain)

    def test_negative_number(self):
        js = "const temp = -40;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("-40", plain)

    def test_hex_number(self):
        js = "const color = 0xFF5733;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("0xFF5733", plain)

    def test_binary_number(self):
        js = "const mask = 0b101010;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("0b101010", plain)

    def test_octal_number(self):
        js = "const perms = 0o755;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("0o755", plain)

    def test_scientific_notation(self):
        js = "const avogadro = 6.022e23;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("6.022e23", plain)

    def test_line_comment(self):
        js = "// Initialize the app\nconst app = createApp();"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Initialize", plain)

    def test_block_comment(self):
        js = "/* Main entry point */\napp.start();"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Main entry point", plain)

    def test_multiline_block_comment(self):
        js = """/*
 * Calculate the factorial
 * @param {number} n
 */
function factorial(n) { return n <= 1 ? 1 : n * factorial(n - 1); }"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("factorial", plain)

    def test_boolean_true(self):
        js = "const enabled = true;"
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_boolean_false(self):
        js = "const disabled = false;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("false", plain)

    def test_null_value(self):
        js = "let data = null;"
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_undefined_value(self):
        js = "let x = undefined;"
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_array_literal(self):
        js = "const nums = [1, 2, 3, 4, 5];"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_object_literal(self):
        js = "const user = { name: 'Alice', age: 30 };"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("Alice", plain)

    def test_destructuring(self):
        js = "const { name, age } = user;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_spread_operator(self):
        js = "const merged = [...arr1, ...arr2];"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("...", plain)

    def test_nullish_coalescing(self):
        js = "const val = data ?? defaultValue;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("??", plain)

    def test_optional_chaining(self):
        js = "const name = user?.profile?.name;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("user", plain)

    def test_ternary_operator(self):
        js = "const status = age >= 18 ? 'adult' : 'minor';"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("adult", plain)

    def test_import_statement(self):
        js = "import { useState, useEffect } from 'react';"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("useState", plain)

    def test_export_statement(self):
        js = "export default function App() {}"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_this_keyword(self):
        js = "this.name = name;"
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_new_keyword(self):
        js = "const user = new User('Alice');"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_typeof_operator(self):
        js = "if (typeof x === 'undefined') { return; }"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("typeof", plain)

    def test_instanceof_operator(self):
        js = "if (obj instanceof Date) { ... }"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("instanceof", plain)

    def test_console_log(self):
        js = 'console.log("Hello, world!");'
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_colors_are_injected(self):
        """Ensure that highlighting actually adds ANSI codes."""
        js = "const x = 42; let y = 'hello';\nif (x > 0) { console.log(y); }"
        result = highlight(js)
        self.assertNotEqual(result, _strip_ansi(result))

    def test_whitespace_preserved(self):
        js = "  const   x   =   42;  \n"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_complex_function(self):
        js = """function fibonacci(n) {
  if (n <= 1) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("fibonacci", plain)

    def test_promise_usage(self):
        js = """fetch('/api/users')
  .then(res => res.json())
  .then(data => console.log(data))
  .catch(err => console.error(err));"""
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("users", plain)

    def test_modulo_operator(self):
        js = "const isEven = n % 2 === 0;"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("%", plain)


class TestJsDiff(unittest.TestCase):
    """Diff highlighting for JavaScript."""

    def test_simple_diff(self):
        old_src = "const x = 1;\n"
        new_src = "const x = 2;\n"
        result = diff_highlight(old_src, new_src)
        self.assertIn("const", _strip_ansi(result))

    def test_add_function(self):
        old_src = "const x = 1;"
        new_src = "const x = 1;\nfunction add(a, b) { return a + b; }"
        result = diff_highlight(old_src, new_src)
        self.assertIn("add", _strip_ansi(result))

    def test_remove_line(self):
        old_src = "const x = 1;\nconsole.log(x);"
        new_src = "const x = 1;"
        result = diff_highlight(old_src, new_src)
        stripped = _strip_ansi(result)
        self.assertIn("-", stripped)

    def test_identical_sources(self):
        src = "const x = 42;"
        result = diff_highlight(src, src)
        self.assertIsInstance(result, str)


class TestJsEdgeCases(unittest.TestCase):
    """Edge cases and malformed input."""

    def test_malformed_js_no_crash(self):
        """Malformed JS should not crash the highlighter."""
        result = highlight("const x = {")
        self.assertIsInstance(result, str)

    def test_unclosed_string(self):
        result = highlight('const msg = "Hello')
        self.assertIsInstance(result, str)

    def test_just_a_comment(self):
        result = highlight("// this is a comment")
        plain = _strip_ansi(result)
        self.assertIn("comment", plain)

    def test_unicode_in_string(self):
        js = 'const greeting = "こんにちは";'
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertIn("こんにちは", plain)

    def test_empty_block(self):
        js = "if (x) {}"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)

    def test_semicolons_only(self):
        js = ";;;"
        result = highlight(js)
        self.assertIsInstance(result, str)

    def test_nested_braces(self):
        js = "{ { { const x = 1; } } }"
        result = highlight(js)
        plain = _strip_ansi(result)
        self.assertEqual(plain, js)


class TestJsShowTrailing(unittest.TestCase):
    """Test trailing whitespace visualization."""

    def test_trailing_spaces_visualized(self):
        result = highlight("const x = 42;   \n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_trailing_tabs_visualized(self):
        result = highlight("let y = true;\t\n", show_trailing=True)
        self.assertIn("\033[1;31m", result)

    def test_no_trailing_no_markers(self):
        result = highlight("const x = 42;\n", show_trailing=True)
        self.assertNotIn("\u00b7", _strip_ansi(result))


if __name__ == "__main__":
    unittest.main()
