
"""Tests for render_markdown.py — rendering, tables, inline formatting, code blocks."""

from __future__ import annotations

import re
import time
import unittest

import render_markdown as rm


def _strip_ansi(s: str) -> str:
    if isinstance(s, str):
        return re.sub(r"\033\[[0-9;]*m", "", s)
    return ""


class TestEmptyInputs(unittest.TestCase):
    """Section 1: empty / None / whitespace inputs."""

    def test_empty_string(self):
        self.assertIs(rm.render_md(""), rm.MD_BLANK)

    def test_whitespace_only(self):
        self.assertIs(rm.render_md("   "), rm.MD_BLANK)

    def test_newlines_only(self):
        self.assertIs(rm.render_md("\n\n\n"), rm.MD_BLANK)

    def test_tabs_only(self):
        self.assertIs(rm.render_md("\t\t\t"), rm.MD_BLANK)

    def test_mixed_whitespace(self):
        self.assertIs(rm.render_md("  \t  \n  "), rm.MD_BLANK)

    def test_null_byte(self):
        result = rm.render_md("\x00")
        self.assertIsNotNone(result)

    def test_null_bytes_in_text(self):
        result = rm.render_md("hello\x00world")
        self.assertIsNotNone(result)

    def test_crlf_whitespace(self):
        self.assertIs(rm.render_md("\r\n\r\n"), rm.MD_BLANK)


class TestHeaders(unittest.TestCase):
    """Section 2: headers."""

    def test_h1_basic(self):
        r = rm.render_md("# Hello World")
        plain = _strip_ansi(r)
        self.assertIn("Hello World", plain)

    def test_h2_basic(self):
        r = rm.render_md("## Sub Header")
        self.assertIn("Sub Header", _strip_ansi(r))

    def test_h3_basic(self):
        r = rm.render_md("### Small Header")
        self.assertIn("Small Header", _strip_ansi(r))

    def test_h4_plain_text(self):
        r = rm.render_md("#### Not a special header")
        self.assertIsNotNone(r)

    def test_h1_with_bold(self):
        r = rm.render_md("# Hello **world**")
        self.assertIsInstance(r, str)

    def test_h1_empty(self):
        self.assertIsNotNone(rm.render_md("# "))

    def test_hash_no_space_not_header(self):
        r = rm.render_md("#Hello")
        self.assertIn("#Hello", _strip_ansi(r))

    def test_h1_just_hashes(self):
        self.assertIsNotNone(rm.render_md("###"))

    def test_header_with_inline_code(self):
        self.assertIsNotNone(rm.render_md("# Use `pip install` to install"))


class TestInlineFormatting(unittest.TestCase):
    """Section 3: inline formatting."""

    def test_bold(self):
        r = rm.render_md("This is **bold** text")
        self.assertIsInstance(r, str)

    def test_italic_star(self):
        r = rm.render_md("This is *italic* text")
        self.assertIsInstance(r, str)

    def test_italic_underscore(self):
        r = rm.render_md("This is _italic_ text")
        self.assertIsInstance(r, str)

    def test_strikethrough(self):
        r = rm.render_md("~~strikethrough~~")
        self.assertIsInstance(r, str)

    def test_inline_code(self):
        r = rm.render_md("Use `code here` to run")
        self.assertIsInstance(r, str)

    def test_link_basic(self):
        r = rm.render_md("[Google](https://google.com)")
        plain = _strip_ansi(r)
        self.assertIn("Google", plain)
        self.assertIn("google.com", plain)

    def test_empty_bold_no_crash(self):
        self.assertIsNotNone(rm.render_md("**"))

    def test_mismatched_bold_no_crash(self):
        self.assertIsNotNone(rm.render_md("This is **bold without closing"))

    def test_unmatched_italic_no_crash(self):
        self.assertIsNotNone(rm.render_md("This is *italic without closing"))

    def test_unmatched_backtick_no_crash(self):
        self.assertIsNotNone(rm.render_md("`code without closing"))

    def test_link_empty_text(self):
        self.assertIsNotNone(rm.render_md("[](url)"))


class TestNestedInline(unittest.TestCase):
    """Section 4: nested / overlapping inline formatting."""

    def test_bold_in_italic(self):
        self.assertIsNotNone(rm.render_md("*This is **bold inside italic** *"))

    def test_italic_in_bold(self):
        self.assertIsNotNone(rm.render_md("**This is *italic inside bold***"))

    def test_triple_star(self):
        self.assertIsNotNone(rm.render_md("***bold and italic***"))

    def test_multiple_bold(self):
        self.assertIsNotNone(rm.render_md("**first** and **second** bold"))

    def test_multiple_codes(self):
        self.assertIsNotNone(rm.render_md("`one` and `two` and `three`"))

    def test_adjacent_formatting(self):
        self.assertIsNotNone(rm.render_md("**bold****bold2**"))

    def test_strikethrough_with_bold(self):
        self.assertIsNotNone(rm.render_md("~~**bold and striked**~~"))


class TestLists(unittest.TestCase):
    """Section 5: lists."""

    def test_dash_list(self):
        plain = _strip_ansi(rm.render_md("- item one"))
        self.assertIn("item one", plain)

    def test_star_list(self):
        plain = _strip_ansi(rm.render_md("* item two"))
        self.assertIn("item two", plain)

    def test_list_with_bold(self):
        self.assertIsNotNone(rm.render_md("- **bold item**"))

    def test_dash_no_space_not_list(self):
        self.assertIsNotNone(rm.render_md("-nospace"))


class TestTables(unittest.TestCase):
    """Section 6: tables — normal and pathological."""

    def _table(self, *rows: str) -> str:
        return "\n".join(rows)

    def test_simple_table(self):
        r = rm.render_md(self._table("| Name | Age |", "|------|-----|", "| Alice | 30 |", "| Bob | 25 |"))
        plain = _strip_ansi(r)
        self.assertIn("Alice", plain)
        self.assertIn("Bob", plain)

    def test_table_no_trailing_pipe(self):
        self.assertIsNotNone(rm.render_md(self._table("| Name | Age |", "|------|-----|", "Alice | 30")))

    def test_table_empty_cells(self):
        self.assertIsNotNone(rm.render_md(self._table("| a || c |", "|-|-|-|", "||b|")))

    def test_table_single_column(self):
        self.assertIsNotNone(rm.render_md(self._table("| Only |", "|------|", "| val |")))

    def test_table_wide_chars(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| 日本語 | 中文 |", "|-------|------|", "| こんにちは | 你好 |"),
        ))

    def test_table_emoji(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| Emoji | Name |", "|-------|------|", "| 😀 | grinning |"),
        ))

    def test_table_center_alignment(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| Left | Center | Right |", "|:-----|:------:|------:|", "| a | b | c |"),
        ))

    def test_table_no_separator_not_table(self):
        self.assertIsNotNone(rm.render_md(self._table("| A | B |", "| 1 | 2 |")))

    def test_table_misaligned_columns(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| A | B |", "|------|-----|", "| 1 |", "| x | y | z |"),
        ))

    def test_table_inline_formatting_in_cells(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| Name | Status |", "|------|--------|",
                         "| **Alice** | `active` |", "| _Bob_ | ~~inactive~~ |"),
        ))

    def test_table_very_wide_cell(self):
        self.assertIsNotNone(rm.render_md(
            self._table("| Short | Long |", "|-------|------|", f"| a | {'x' * 200} |"),
        ))

    def test_table_many_columns(self):
        cols = "|".join([f" C{i} " for i in range(20)])
        sep = "|".join([" --- " for _ in range(20)])
        row = "|".join([f" v{i} " for i in range(20)])
        self.assertIsNotNone(rm.render_md(f"|{cols}|\n|{sep}|\n|{row}|"))

    def test_table_many_rows(self):
        rows = "\n".join([f"| Row{i} | Val{i} |" for i in range(100)])
        self.assertIsNotNone(rm.render_md(f"| Name | Value |\n|------|-------|\n{rows}"))

    
    def test_parse_table_row_basic(self):
        self.assertEqual(rm._parse_table_row("| a | b | c |"), ["a", "b", "c"])

    def test_parse_table_row_no_leading_pipe(self):
        self.assertEqual(rm._parse_table_row("a | b | c"), ["a", "b", "c"])

    def test_parse_table_row_empty_cells(self):
        self.assertEqual(len(rm._parse_table_row("|||")), 2)

    def test_parse_table_row_three_empty_cells(self):
        self.assertEqual(len(rm._parse_table_row("||||")), 3)

    def test_parse_table_alignment_left(self):
        a = rm._parse_table_alignment("| --- | --- |")
        self.assertTrue(all(x == "left" for x in a))

    def test_parse_table_alignment_center(self):
        a = rm._parse_table_alignment("| :---: | :---: |")
        self.assertTrue(all(x == "center" for x in a))

    def test_parse_table_alignment_right(self):
        a = rm._parse_table_alignment("| ---: | ---: |")
        self.assertTrue(all(x == "right" for x in a))


class TestXmlToolBlocks(unittest.TestCase):
    """Section 7: XML tool blocks."""

    def test_shell_basic(self):
        r = rm.render_md("<shell>\necho hello\n</shell>")
        self.assertIsInstance(r, str)

    def test_write_basic(self):
        r = rm.render_md('<write path="test.py">\nprint("hi")\n</write>')
        self.assertIsInstance(r, str)

    def test_edit_basic(self):
        r = rm.render_md(
            '<edit path="test.py">\n<find>\nold\n</find>\n'
            '<replace>\nnew\n</replace>\n</edit>',
        )
        self.assertIsInstance(r, str)

    def test_shell_remote(self):
        self.assertIsInstance(rm.render_md('<shell remote="user@host">\nls -la\n</shell>'), str)

    def test_write_special_chars(self):
        code = 'x = "hello <world> & \\"quotes\\""'
        self.assertIsNotNone(rm.render_md(f'<write path="test.py">\n{code}\n</write>'))

    def test_shell_empty(self):
        self.assertIsNotNone(rm.render_md("<shell>\n</shell>"))

    def test_malformed_xml_unclosed(self):
        self.assertIsNotNone(rm.render_md("<shell>\necho hello"))

    def test_shell_multiline(self):
        code = "\n".join([f"echo line{i}" for i in range(50)])
        self.assertIsNotNone(rm.render_md(f"<shell>\n{code}\n</shell>"))


class TestUnicode(unittest.TestCase):
    """Section 8: unicode stress."""

    def test_cjk_header(self):
        self.assertIsNotNone(rm.render_md("# こんにちは世界"))

    def test_chinese_header(self):
        self.assertIsNotNone(rm.render_md("## 中文标题"))

    def test_arabic_text(self):
        self.assertIsNotNone(rm.render_md("مرحبا بالعالم"))

    def test_emoji_header(self):
        self.assertIsNotNone(rm.render_md("# 😀 Hello 🌍 World 🔥"))

    def test_combining_characters(self):
        self.assertIsNotNone(rm.render_md("# caf\u0065\u0301"))

    def test_zero_width_joiner(self):
        self.assertIsNotNone(rm.render_md("👨‍👩‍👧‍👦 family emoji"))

    def test_mixed_scripts(self):
        self.assertIsNotNone(rm.render_md("# Hello 世界 مرحبا שלום 🌍"))

    def test_display_width_cjk(self):
        self.assertEqual(rm._display_width("こんにちは"), 10)

    def test_display_width_mixed(self):
        self.assertEqual(rm._display_width("Hi世界"), 6)

    def test_ansi_display_width_with_codes(self):
        self.assertEqual(rm._ansi_display_width("\033[1mHello\033[0m"), 5)


class TestPerformance(unittest.TestCase):
    """Section 9: long content performance."""

    def test_long_line_speed(self):
        start = time.time()
        rm.render_md("a" * 10000)
        self.assertLess(time.time() - start, 5.0)

    def test_many_lines_speed(self):
        lines = "\n".join([f"- item {i}" for i in range(1000)])
        start = time.time()
        rm.render_md(lines)
        self.assertLess(time.time() - start, 5.0)

    def test_huge_table_speed(self):
        rows = "\n".join([f"| Col{i} | Val{i} | Data{i} |" for i in range(500)])
        table = f"| A | B | C |\n|---|---|---|\n{rows}"
        start = time.time()
        rm.render_md(table)
        self.assertLess(time.time() - start, 10.0)


class TestAdversarial(unittest.TestCase):
    """Section 10: malformed / adversarial input."""

    def test_bold_backtracking_trap(self):
        start = time.time()
        rm.render_md("**" * 500 + "x")
        self.assertLess(time.time() - start, 2.0)

    def test_italic_backtracking_trap(self):
        start = time.time()
        rm.render_md("*" * 500 + "x")
        self.assertLess(time.time() - start, 2.0)

    def test_nested_backticks(self):
        self.assertIsNotNone(rm.render_md("``````code`````"))

    def test_xml_injection_attempt(self):
        self.assertIsNotNone(rm.render_md("<shell><script>alert(1)</script></shell>"))

    def test_repeated_pipe_bomb(self):
        self.assertIsNotNone(rm.render_md("|" * 10000))

    def test_control_characters(self):
        self.assertIsNotNone(rm.render_md("".join(chr(i) for i in range(32))))


class TestFencedCodeBlocks(unittest.TestCase):
    """Section 10.5: fenced code blocks."""

    def _cb(self, lang: str, code: str) -> str:
        return f"```{lang}\n{code}\n```"

    def test_python_block(self):
        plain = _strip_ansi(rm.render_md(self._cb("python", "def f(): pass")))
        self.assertIn("def", plain)

    def test_bash_block(self):
        plain = _strip_ansi(rm.render_md(self._cb("bash", "echo hello")))
        self.assertIn("echo", plain)

    def test_html_block(self):
        plain = _strip_ansi(rm.render_md(self._cb("html", "<div>hi</div>")))
        self.assertIn("<div>", plain)

    def test_no_lang(self):
        plain = _strip_ansi(rm.render_md("```\nplain text\n```"))
        self.assertIn("plain text", plain)

    def test_single_line(self):
        self.assertIsNotNone(rm.render_md(self._cb("python", "x = 1")))

    def test_many_lines(self):
        lines = "\n".join([f"line_{i} = {i}" for i in range(50)])
        self.assertIsNotNone(rm.render_md(self._cb("python", lines)))

    def test_unknown_lang(self):
        self.assertIsNotNone(rm.render_md(self._cb("rust", "fn main() {}")))

    def test_empty_body(self):
        self.assertIsNotNone(rm.render_md("```python\n```"))

    def test_special_chars_in_code(self):
        self.assertIsNotNone(rm.render_md(self._cb("python", 'x = "hello <world>"')))

    def test_alias_py(self):
        plain = _strip_ansi(rm.render_md(self._cb("py", "print(1)")))
        self.assertIn("print", plain)

    def test_alias_sh(self):
        plain = _strip_ansi(rm.render_md(self._cb("sh", "ls -la")))
        self.assertIn("ls", plain)

    def test_unicode_code(self):
        code = "# こんにちは\ndef greet():\n    print('你好')\n    emoji = '😀'"
        self.assertIsNotNone(rm.render_md(self._cb("python", code)))

    def test_unclosed_fence(self):
        self.assertIsNotNone(rm.render_md("```python\nno closing fence"))


class TestStreamingCodeBlocks(unittest.TestCase):
    """Section 10.6: simulated streaming code block buffering."""

    def _build_processor(self):
        """Return (process_line, flush_final) with shared state."""
        _code_buffer: list[str] = []
        _in_code_block = False

        def process_line(line: str) -> str:
            nonlocal _code_buffer, _in_code_block
            stripped = line.strip()
            if stripped.startswith("```"):
                if not _in_code_block:
                    _in_code_block = True
                    _code_buffer = [line]
                    return "STARTED_CODE_BLOCK"
                else:
                    _code_buffer.append(line)
                    block = "\n".join(_code_buffer)
                    _code_buffer = []
                    _in_code_block = False
                    return f"CODE_BLOCK_COMPLETE:{len(block)}chars"
            if _in_code_block:
                _code_buffer.append(line)
                return "BUFFERED_IN_CODE"
            return f"PLAIN:{line}"

        def flush_final() -> str | None:
            nonlocal _code_buffer, _in_code_block
            if _code_buffer:
                block = "\n".join(_code_buffer)
                _code_buffer = []
                _in_code_block = False
                return f"FINAL_FLUSH:{block}"
            return None

        return process_line, flush_final

    def test_basic_buffering(self):
        proc, _ = self._build_processor()
        results = [proc(l) for l in [
            "Here is some markdown text",
            "```python",
            "def hello():",
            "    print('world')",
            "```",
            "More text after the code block",
        ]]
        self.assertEqual(results[0], "PLAIN:Here is some markdown text")
        self.assertEqual(results[1], "STARTED_CODE_BLOCK")
        self.assertEqual(results[2], "BUFFERED_IN_CODE")
        self.assertEqual(results[3], "BUFFERED_IN_CODE")
        self.assertTrue(results[4].startswith("CODE_BLOCK_COMPLETE:"))
        self.assertEqual(results[5], "PLAIN:More text after the code block")

    def test_multiple_blocks(self):
        proc, _ = self._build_processor()
        results = [proc(l) for l in [
            "# Header",
            "```bash",
            "echo hello",
            "```",
            "- list item",
            "```python",
            "x = 1",
            "```",
        ]]
        self.assertEqual(results[0], "PLAIN:# Header")
        self.assertEqual(results[1], "STARTED_CODE_BLOCK")
        self.assertEqual(results[2], "BUFFERED_IN_CODE")
        self.assertTrue(results[3].startswith("CODE_BLOCK_COMPLETE:"))
        self.assertEqual(results[4], "PLAIN:- list item")
        self.assertEqual(results[5], "STARTED_CODE_BLOCK")
        self.assertEqual(results[6], "BUFFERED_IN_CODE")
        self.assertTrue(results[7].startswith("CODE_BLOCK_COMPLETE:"))

    def test_incomplete_flush(self):
        proc, flush = self._build_processor()
        results = [proc(l) for l in ["```python", "def incomplete():", "    pass"]]
        self.assertEqual(results[0], "STARTED_CODE_BLOCK")
        self.assertEqual(results[1], "BUFFERED_IN_CODE")
        final = flush()
        self.assertIsNotNone(final)
        self.assertIn("incomplete", final)


class TestHelpers(unittest.TestCase):
    """Section 11: helper functions & edge cases."""

    def test_visible_len_plain(self):
        self.assertEqual(rm._visible_len("hello"), 5)

    def test_visible_len_with_ansi(self):
        self.assertEqual(rm._visible_len("\033[1mhello\033[0m"), 5)

    def test_pad_to_with_ansi(self):
        result = rm._pad_to("\033[1mHi\033[0m", 5)
        self.assertEqual(rm._visible_len(result), 5)

    def test_is_table_line_yes(self):
        self.assertTrue(rm._is_table_line("| a | b |"))

    def test_is_table_line_no(self):
        self.assertFalse(rm._is_table_line("just text"))

    def test_is_table_separator_yes(self):
        self.assertTrue(rm._is_table_separator("|---|---|"))

    def test_is_table_separator_no(self):
        self.assertFalse(rm._is_table_separator("| a | b |"))

    def test_render_table_block_none(self):
        self.assertIsNone(rm.render_table_block("not a table"))

    def test_md_blank_identity(self):
        self.assertIs(rm.render_md(""), rm.MD_BLANK)
        self.assertIs(rm.render_md("   "), rm.MD_BLANK)
        self.assertIs(rm.render_md("  \n  "), rm.MD_BLANK)


if __name__ == "__main__":
    unittest.main()