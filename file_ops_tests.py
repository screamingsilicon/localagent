
"""Tests for file_ops module."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from unittest import TestCase, main

from file_ops import (
    MAX_FILE_SIZE,
    _is_path_escape,
    check_syntax,
    find_and_replace,
    format_diff,
    normalize_text,
    read_file,
    strip_bom,
    write_file,
)


class TestNormalizeText(TestCase):
    def test_crlf_to_lf(self):
        self.assertEqual(normalize_text("a\r\nb"), "a\nb")

    def test_cr_to_lf(self):
        self.assertEqual(normalize_text("a\rb"), "a\nb")

    def test_already_lf(self):
        self.assertEqual(normalize_text("a\nb"), "a\nb")

    def test_strips_trailing_whitespace(self):
        self.assertEqual(normalize_text("hello   \nworld\t\n"), "hello\nworld\n")

    def test_curly_quotes(self):
        self.assertEqual(normalize_text("'quote'"), "'quote'")
        self.assertEqual(normalize_text('"quote"'), '"quote"')

    def test_unicode_dashes(self):
        
        text = "a\u2013b\u2014c\u2012d\u2212e"
        self.assertEqual(normalize_text(text), "a-b-c-d-e")

    def test_nonbreaking_spaces(self):
        
        text = "a\u00a0b\u2003c\u2009d\u3000e"
        self.assertEqual(normalize_text(text), "a b c d e")

    def test_strict_mode_preserves_whitespace(self):
        self.assertEqual(normalize_text("hello   \n", strict=True), "hello   \n")

    def test_strict_mode_only_line_endings(self):
        self.assertEqual(normalize_text("a\r\nb  ", strict=True), "a\nb  ")


class TestCheckSyntax(TestCase):
    def test_valid_python(self):
        ok, err = check_syntax("foo.py", "x = 1 + 2")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_invalid_python(self):
        ok, err = check_syntax("bad.py", "def foo(:")
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertIn("syntax", err.lower())

    def test_non_python_file_ignored(self):
        ok, err = check_syntax("readme.txt", "this is not python at all (")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_pyi_file_checked(self):
        ok, err = check_syntax("stub.pyi", "def foo() -> None: ...")
        self.assertTrue(ok)
        self.assertIsNone(err)


class TestFindAndReplace(TestCase):
    def test_exact_match_single_line(self):
        content = "hello world\nfoo bar"
        base, new, start, end = find_and_replace(content, "world", "earth", "f.txt")
        self.assertEqual(new, "hello earth\nfoo bar")
        self.assertEqual(start, 1)
        self.assertEqual(end, 1)

    def test_exact_match_multi_line(self):
        content = "line1\nline2\nline3"
        base, new, start, end = find_and_replace(content, "line2\nline3", "replaced", "f.txt")
        self.assertEqual(new, "line1\nreplaced")
        self.assertEqual(start, 2)
        self.assertEqual(end, 3)

    def test_fuzzy_match_trailing_whitespace(self):
        content = "hello world   \nfoo bar\t"
        old = "hello world\nfoo bar"  
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_match_curly_quotes(self):
        content = "say 'hello'\n"
        old = "say 'hello'"  
        base, new, start, end = find_and_replace(content, old, "say 'bye'", "f.txt", strict=False)
        self.assertIn("bye", new)

    def test_strict_rejects_fuzzy(self):
        content = "hello world   \n"
        old = "hello world\n"  
        with self.assertRaises(ValueError):
            find_and_replace(content, old, "replaced", "f.txt", strict=True)

    def test_multiple_exact_matches_raises(self):
        content = "abc\nabc"
        with self.assertRaises(ValueError):
            find_and_replace(content, "abc", "xyz", "f.txt")

    def test_multiple_fuzzy_matches_raises(self):
        content = "hello   \nhello  \n"
        old = "hello"
        with self.assertRaises(ValueError):
            find_and_replace(content, old, "world", "f.txt", strict=False)

    def test_not_found_raises(self):
        with self.assertRaises(ValueError):
            find_and_replace("hello", "goodbye", "world", "f.txt")

    def test_empty_old_text_raises(self):
        with self.assertRaises(ValueError):
            find_and_replace("hello", "", "world", "f.txt")

    def test_line_numbers_at_start_of_file(self):
        content = "target\nrest"
        _, _, start, end = find_and_replace(content, "target", "replaced", "f.txt")
        self.assertEqual(start, 1)
        self.assertEqual(end, 1)

    def test_line_numbers_at_end_of_file(self):
        content = "first\nsecond\nthird"
        _, _, start, end = find_and_replace(content, "third", "last", "f.txt")
        self.assertEqual(start, 3)
        self.assertEqual(end, 3)


class TestFormatDiff(TestCase):
    def test_no_changes(self):
        diff = format_diff("same\n", "same\n")
        self.assertEqual(diff, "")

    def test_added_line(self):
        diff = format_diff("a\n", "a\nb\n")
        self.assertIn("+b", diff)

    def test_removed_line(self):
        diff = format_diff("a\nb\n", "a\n")
        self.assertIn("-b", diff)

    def test_modified_line(self):
        diff = format_diff("hello\n", "world\n")
        self.assertIn("-hello", diff)
        self.assertIn("+world", diff)

    def test_hunk_headers_hidden(self):
        diff = format_diff("a\nb\nc\n", "a\nx\nc\n")
        
        for line in diff.splitlines():
            self.assertNotIn("@@", line)


class TestIsPathEscape(TestCase):
    def test_relative_path_safe(self):
        self.assertFalse(_is_path_escape("/workspace", "foo/bar.txt"))

    def test_dotdot_escapes(self):
        self.assertTrue(_is_path_escape("/workspace", "../../../etc/passwd"))

    def test_absolute_outside_escapes(self):
        self.assertTrue(_is_path_escape("/workspace", "/tmp/secret"))

    def test_deep_nested_safe(self):
        self.assertFalse(_is_path_escape("/workspace", "a/b/c/d/e.txt"))


class TestReadFileLocal(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_read_existing_file(self):
        path = Path(self.tmpdir) / "hello.txt"
        path.write_text("hello world")
        content, err = read_file(str(path), self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual(content, "hello world")

    def test_read_not_found(self):
        content, err = read_file("nonexistent.txt", self.tmpdir)
        self.assertIsNone(content)
        self.assertEqual(err, "not found")

    def test_read_empty_file(self):
        path = Path(self.tmpdir) / "empty.txt"
        path.write_text("")
        content, err = read_file(str(path), self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual(content, "[empty]")

    def test_path_escape_denied(self):
        content, err = read_file("../../etc/passwd", self.tmpdir)
        self.assertIsNone(content)
        self.assertEqual(err, "path_escapes")

    def test_path_escape_allowed(self):
        
        content, err = read_file("/workspace/file_ops.py", "/tmp", allow_escape=True)
        self.assertIsNone(err)
        self.assertIn("normalize_text", content)

    def test_read_directory_rejected(self):
        content, err = read_file(".", self.tmpdir)
        self.assertIsNone(content)
        self.assertEqual(err, "not a regular file")

    def test_read_binary_rejected(self):
        path = Path(self.tmpdir) / "binary.bin"
        path.write_bytes(bytes(range(256)))
        content, err = read_file("binary.bin", self.tmpdir)
        self.assertIsNone(content)
        self.assertEqual(err, "binary/not UTF-8")

    def test_relative_path_resolved(self):
        subdir = Path(self.tmpdir) / "sub"
        subdir.mkdir()
        (subdir / "inner.txt").write_text("deep content")
        content, err = read_file("sub/inner.txt", self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual(content, "deep content")


class TestWriteFileLocal(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_write_new_file(self):
        err = write_file("new.txt", "content here", self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual((Path(self.tmpdir) / "new.txt").read_text(), "content here")

    def test_overwrite_existing_file(self):
        path = Path(self.tmpdir) / "exists.txt"
        path.write_text("old")
        err = write_file("exists.txt", "new content", self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual(path.read_text(), "new content")

    def test_write_creates_parent_dirs(self):
        err = write_file("a/b/c/deep.txt", "deep", self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual((Path(self.tmpdir) / "a/b/c/deep.txt").read_text(), "deep")

    def test_path_escape_denied(self):
        err = write_file("../../tmp/evil.txt", "bad", self.tmpdir)
        self.assertEqual(err, "path_escapes")

    def test_path_escape_allowed(self):
        target = Path(self.tmpdir).parent / "escape_test.txt"
        try:
            err = write_file("../escape_test.txt", "escaped", self.tmpdir, allow_escape=True)
            self.assertIsNone(err)
            self.assertEqual(target.read_text(), "escaped")
        finally:
            target.unlink(missing_ok=True)

    def test_write_empty_content(self):
        err = write_file("empty.txt", "", self.tmpdir)
        self.assertIsNone(err)
        self.assertEqual((Path(self.tmpdir) / "empty.txt").read_text(), "")


class TestStripBom(TestCase):
    """BOM handling tests."""

    def test_strip_bom_basic(self):
        text = "\ufeffprint('hello')\n"
        cleaned, had_bom = strip_bom(text)
        self.assertTrue(had_bom)
        self.assertEqual(cleaned, "print('hello')\n")
        self.assertNotIn("\ufeff", cleaned)

    def test_strip_bom_no_bom(self):
        text = "print('hello')\n"
        cleaned, had_bom = strip_bom(text)
        self.assertFalse(had_bom)
        self.assertEqual(cleaned, text)


class TestBomInNormalize(TestCase):
    """normalize_text() strips BOM before any other processing."""

    def test_normalize_strips_bom(self):
        text = "\ufeffline1\r\nline2  \r\n"
        result = normalize_text(text)
        self.assertNotIn("\ufeff", result)
        self.assertEqual(result, "line1\nline2\n")

    def test_normalize_strict_strips_bom(self):
        text = "\ufeffhello  \nworld  "
        result = normalize_text(text, strict=True)
        self.assertNotIn("\ufeff", result)
        self.assertEqual(result, "hello  \nworld  ")


class TestBomEdit(TestCase):
    """find_and_replace on BOM content matches without BOM in old_text."""

    def test_edit_with_bom_file(self):
        raw_content = "\ufeffdef hello():\n    print('world')\n"
        content = normalize_text(raw_content)
        result = find_and_replace(
            content,
            "def hello():\n    print('world')",
            "def hello():\n    print('universe')",
            path="bom_test.py",
        )
        base, new_content, start, end = result
        self.assertIn("universe", new_content)

    def test_e2e_edit_bom_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8-sig"
        ) as f:
            f.write("def old_func():\n    return 42\n")
            fpath = f.name

        try:
            raw = open(fpath, "r", encoding="utf-8").read()
            content = normalize_text(raw)
            self.assertNotIn("\ufeff", content)

            result = find_and_replace(content, "return 42", "return 100", path=fpath)
            base, new_content, start, end = result
            self.assertIn("return 100", new_content)
        finally:
            os.unlink(fpath)

    def test_e2e_edit_bom_file_no_bom_in_find(self):
        raw_content = "\ufeff# -*- coding: utf-8 -*-\nVALUE = 1\n"
        content = normalize_text(raw_content)

        result = find_and_replace(content, "VALUE = 1", "VALUE = 2", path="test.py")
        base, new_content, start, end = result
        self.assertIn("VALUE = 2", new_content)


class TestFuzzyMatchCrlf(TestCase):
    """Fuzzy matching: CRLF/CR line ending tolerance."""

    def test_fuzzy_crlf_to_lf(self):
        content = "hello world\r\nfoo bar\r\n"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_cr_to_lf(self):
        content = "hello world\rfoo bar\r"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_mixed_line_endings(self):
        content = "line1\r\nline2\rline3\n"
        old = "line1\nline2\nline3\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_model_crlf_file_lf(self):
        content = "hello world\nfoo bar\n"
        old = "hello world\r\nfoo bar\r\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)


class TestFuzzyMatchTrailingWs(TestCase):
    """Fuzzy matching: trailing whitespace tolerance."""

    def test_fuzzy_trailing_spaces(self):
        content = "hello world   \nfoo bar  \n"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_trailing_tabs(self):
        content = "hello world\t\t\nfoo bar\t\n"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_trailing_mixed_ws(self):
        content = "hello world  \t  \nfoo bar\t  \n"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_model_has_trailing_file_doesnt(self):
        content = "hello world\nfoo bar\n"
        old = "hello world  \nfoo bar  \n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)


class TestFuzzyMatchUnicode(TestCase):
    """Fuzzy matching: Unicode normalization (smart quotes, dashes, special spaces)."""

    def test_fuzzy_smart_single_quotes(self):
        content = "'hello'\n"
        old = "\u2018hello\u2019\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_smart_double_quotes(self):
        content = '"hello"\n'
        old = "\u201chello\u201d\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_en_dash(self):
        content = "a-b\n"
        old = "a\u2013b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_em_dash(self):
        content = "a-b\n"
        old = "a\u2014b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_nbsp(self):
        content = "a b\n"
        old = "a\u00a0b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_ideographic_space(self):
        content = "a b\n"
        old = "a\u3000b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_minus_sign(self):
        content = "a-b\n"
        old = "a\u2212b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)


class TestFuzzyMatchCombined(TestCase):
    """Fuzzy matching: combined issues."""

    def test_fuzzy_crlf_plus_trailing_ws(self):
        content = "hello world   \r\nfoo bar  \r\n"
        old = "hello world\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_smart_quotes_plus_trailing_ws(self):
        content = "'hello'   \n"
        old = "\u2018hello\u2019\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_all_issues_combined(self):
        content = "'hello'   \r\nfoo bar  \r\n"
        old = "\u2018hello\u2019\nfoo bar\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_model_smart_quotes_file_ascii(self):
        content = "'hello'\n"
        old = "\u2018hello\u2019\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_model_nbsp_file_regular_space(self):
        content = "a b c\n"
        old = "a\u00a0b\u2003c\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_model_emdash_file_hyphen(self):
        content = "a-b\n"
        old = "a\u2014b\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)


class TestFuzzyMatchStrict(TestCase):
    """Strict mode rejects fuzzy matches."""

    def test_strict_mode_rejects_fuzzy(self):
        content = "hello world   \n"
        old = "hello world\n"
        with self.assertRaises(ValueError):
            find_and_replace(content, old, "replaced", "f.txt", strict=True)

    def test_strict_mode_accepts_exact(self):
        content = "hello world\n"
        old = "hello world\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=True)
        self.assertIn("replaced", new)


class TestFuzzyMatchEdgeCases(TestCase):
    """Fuzzy matching edge cases."""

    def test_fuzzy_match_result_not_found(self):
        with self.assertRaises(ValueError):
            find_and_replace("hello world\n", "goodbye\n", "replaced", "f.txt", strict=False)

    def test_fuzzy_single_line_no_newline(self):
        content = "hello world"
        old = "hello world  "
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_match_at_end_of_file(self):
        content = "first\nsecond\nthird"
        old = "third  "
        base, new, start, end = find_and_replace(content, old, "last", "f.txt", strict=False)
        self.assertIn("last", new)

    def test_fuzzy_match_at_start_of_file(self):
        content = "hello   \nworld"
        old = "hello\n"
        base, new, start, end = find_and_replace(content, old, "hi\n", "f.txt", strict=False)
        self.assertIn("hi", new)

    def test_fuzzy_preserves_unchanged_content(self):
        content = "alpha\nhello world   \nbeta\n"
        old = "hello world\n"
        base, new, start, end = find_and_replace(content, old, "goodbye earth\n", "f.txt", strict=False)
        self.assertIn("goodbye earth", new)
        self.assertIn("alpha", new)
        self.assertIn("beta", new)

    def test_fuzzy_multiline_with_unicode(self):
        content = "line1\r\n'hello world'  \r\nline3\n"
        old = "line1\n\u2018hello world\u2019\nline3\n"
        base, new, start, end = find_and_replace(content, old, "replaced", "f.txt", strict=False)
        self.assertIn("replaced", new)

    def test_fuzzy_preserves_bom_in_output(self):
        content = "\ufeffhello world   \n"
        old = "hello world\n"
        base, new, start, end = find_and_replace(content, old, "goodbye earth\n", "f.txt", strict=False)
        self.assertIn("\ufeff", new)
        self.assertIn("goodbye earth", new)

    def test_error_message_helpful_for_not_found(self):
        try:
            find_and_replace("hello world\n", "not here\n", "replaced", "f.txt")
            self.fail("Should have raised ValueError")
        except ValueError as e:
            self.assertIn("not found", str(e).lower())


class TestMaxFileSize(TestCase):
    def test_constant_value(self):
        self.assertEqual(MAX_FILE_SIZE, 256 * 1024)


if __name__ == "__main__":
    main(verbosity=2)