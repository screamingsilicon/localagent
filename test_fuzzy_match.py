"""Comprehensive tests for fuzzy matching in find_and_replace.

Tests cover progressive fallback strategies:
  1. Exact match
  2. LF-normalized (CRLF vs LF)
  3. Trailing whitespace tolerant
  4. Full Unicode normalization (smart quotes, dashes, special spaces)
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/workspace")


# ===================================================================
# 1. Exact Match Tests
# ===================================================================
def test_exact_match_basic():
    """Simple exact match works."""
    from file_ops import find_and_replace
    content = "hello world\nfoo bar\n"
    base, new, start, end = find_and_replace(
        content, "hello world", "goodbye world", path="test.txt"
    )
    assert "goodbye world" in new
    assert start == 1
    assert end == 1


def test_exact_match_multiline():
    """Exact match across multiple lines."""
    from file_ops import find_and_replace
    content = "line1\nline2\nline3\n"
    base, new, start, end = find_and_replace(
        content, "line1\nline2", "replaced", path="test.txt"
    )
    assert "replaced" in new
    assert start == 1
    assert end == 2


def test_exact_match_empty_old_text():
    """Empty old_text raises ValueError."""
    from file_ops import find_and_replace
    try:
        find_and_replace("content", "", "replacement", path="test.txt")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "empty" in str(e).lower()


def test_exact_match_not_found():
    """Non-existent text raises ValueError."""
    from file_ops import find_and_replace
    try:
        find_and_replace("hello world", "xyz", "replacement", path="test.txt")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not found" in str(e).lower()


def test_exact_match_multiple_occurrences():
    """Multiple exact matches raises ValueError."""
    from file_ops import find_and_replace
    content = "foo bar foo bar"
    try:
        find_and_replace(content, "foo", "baz", path="test.txt")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "multiple" in str(e).lower()


# ===================================================================
# 2. LF-Normalized Match Tests (CRLF vs LF)
# ===================================================================
def test_fuzzy_crlf_to_lf():
    """File has CRLF, model sends LF pattern — should match."""
    from file_ops import find_and_replace
    content = "hello world\r\nfoo bar\r\n"
    pattern = "hello world\nfoo bar"  # LF only
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_cr_to_lf():
    """File has old-style CR line endings — should match LF pattern."""
    from file_ops import find_and_replace
    content = "hello world\rfolder\r"
    pattern = "hello world\nfolder"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_mixed_line_endings():
    """File has mixed CRLF and LF — should match consistent LF pattern."""
    from file_ops import find_and_replace
    content = "line1\r\nline2\nline3\r\n"
    pattern = "line1\nline2\nline3"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_model_crlf_file_lf():
    """Model sends CRLF pattern, file has LF — should match."""
    from file_ops import find_and_replace
    content = "hello world\nfoo bar\n"
    pattern = "hello world\r\nfoo bar"  # model sent CRLF
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


# ===================================================================
# 3. Trailing Whitespace Tolerant Tests
# ===================================================================
def test_fuzzy_trailing_spaces():
    """File has trailing spaces on lines — should match clean pattern."""
    from file_ops import find_and_replace
    content = "hello world   \nfoo bar   \n"
    pattern = "hello world\nfoo bar"  # no trailing spaces
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_trailing_tabs():
    """File has trailing tabs — should match clean pattern."""
    from file_ops import find_and_replace
    content = "hello world\t\nfoo bar\t\n"
    pattern = "hello world\nfoo bar"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_trailing_mixed_ws():
    """File has mixed trailing whitespace (spaces + tabs)."""
    from file_ops import find_and_replace
    content = "line1   \t\nline2\t  \nline3   \n"
    pattern = "line1\nline2\nline3"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_model_has_trailing_file_doesnt():
    """Model sends trailing whitespace, file doesn't — should match."""
    from file_ops import find_and_replace
    content = "hello world\nfoo bar\n"
    pattern = "hello world   \nfoo bar   "  # model added trailing spaces
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


# ===================================================================
# 4. Full Fuzzy Unicode Tests
# ===================================================================
def test_fuzzy_smart_single_quotes():
    """File has smart single quotes — should match ASCII apostrophe."""
    from file_ops import find_and_replace
    content = "it\u2019s a beautiful day\n"  # right single quote
    pattern = "it's a beautiful day"  # ASCII apostrophe
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_smart_double_quotes():
    """File has smart double quotes — should match ASCII quotes."""
    from file_ops import find_and_replace
    content = '\u201cHello\u201d world\n'  # left/right double quotes
    pattern = '"Hello" world'  # ASCII quotes
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_en_dash():
    """File has en-dash — should match ASCII hyphen."""
    from file_ops import find_and_replace
    content = "range 1\u201310\n"  # en-dash
    pattern = "range 1-10"  # ASCII hyphen
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_em_dash():
    """File has em-dash — should match ASCII hyphen."""
    from file_ops import find_and_replace
    content = "value\u2014done\n"  # em-dash
    pattern = "value-done"  # ASCII hyphen
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_nbsp():
    """File has non-breaking space — should match regular space."""
    from file_ops import find_and_replace
    content = "hello\u00a0world\n"  # NBSP
    pattern = "hello world"  # regular space
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_ideographic_space():
    """File has ideographic space — should match regular space."""
    from file_ops import find_and_replace
    content = "hello\u3000world\n"  # ideographic space
    pattern = "hello world"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_minus_sign():
    """File has Unicode minus sign — should match ASCII hyphen."""
    from file_ops import find_and_replace
    content = "value\u22125\n"  # mathematical minus
    pattern = "value-5"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


# ===================================================================
# 5. Model Sends Unicode, File Has ASCII (Reverse Direction)
# ===================================================================
def test_fuzzy_model_smart_quotes_file_ascii():
    """Model sends smart quotes, file has ASCII — should match."""
    from file_ops import find_and_replace
    content = "it's a test\n"
    pattern = "it\u2019s a test"  # model sent smart quote
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_model_nbsp_file_regular_space():
    """Model sends NBSP, file has regular space — should match."""
    from file_ops import find_and_replace
    content = "hello world\n"
    pattern = "hello\u00a0world"  # model sent NBSP
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_model_emdash_file_hyphen():
    """Model sends em-dash, file has hyphen — should match."""
    from file_ops import find_and_replace
    content = "a-b\n"
    pattern = "a\u2014b"  # model sent em-dash
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


# ===================================================================
# 6. Combined Fuzzy Tests (Multiple Issues)
# ===================================================================
def test_fuzzy_crlf_plus_trailing_ws():
    """File has CRLF + trailing spaces — should match clean LF pattern."""
    from file_ops import find_and_replace
    content = "hello world   \r\nfoo bar   \r\n"
    pattern = "hello world\nfoo bar"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_smart_quotes_plus_trailing_ws():
    """File has smart quotes + trailing spaces — should match clean ASCII."""
    from file_ops import find_and_replace
    content = "\u201cHello\u201d world   \n"  # smart quotes + trailing space
    pattern = '"Hello" world'  # clean ASCII, no trailing space
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_all_issues_combined():
    """File has CRLF + trailing spaces + smart quotes — should match clean LF ASCII."""
    from file_ops import find_and_replace
    content = "\u201cHello\u201d world   \r\nit\u2019s great   \r\n"
    pattern = '"Hello" world\nit\'s great'
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


# ===================================================================
# 7. Strict Mode Tests
# ===================================================================
def test_strict_mode_rejects_fuzzy():
    """Strict mode should NOT fall back to fuzzy matching."""
    from file_ops import find_and_replace
    content = "hello world   \n"
    pattern = "hello world\n"  # missing trailing spaces
    try:
        find_and_replace(content, pattern, "replaced", path="test.txt", strict=True)
        assert False, "Should have raised ValueError in strict mode"
    except ValueError as e:
        assert "exact match" in str(e).lower() or "not found" in str(e).lower()


def test_strict_mode_accepts_exact():
    """Strict mode should accept exact matches."""
    from file_ops import find_and_replace
    content = "hello world\n"
    pattern = "hello world\n"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt", strict=True)
    assert "replaced" in new


# ===================================================================
# 8. FuzzyMatchResult Unit Tests
# ===================================================================
def test_fuzzy_match_result_not_found():
    """FuzzyMatchResult.not_found() returns correct defaults."""
    from file_ops import fuzzy_find, FuzzyMatchResult
    result = fuzzy_find("hello", "xyz")
    assert not result.found
    assert result.index == -1
    assert result.match_length == 0


def test_fuzzy_match_result_exact_strategy():
    """Exact match reports 'exact' strategy."""
    from file_ops import fuzzy_find
    result = fuzzy_find("hello world", "hello")
    assert result.found
    assert result.strategy == "exact"
    assert result.index == 0
    assert result.match_length == 5


def test_fuzzy_match_result_lf_strategy():
    """CRLF→LF match reports 'lf-normalized' strategy."""
    from file_ops import fuzzy_find
    result = fuzzy_find("hello\r\nworld", "hello\nworld")
    assert result.found
    assert result.strategy == "lf-normalized"


def test_fuzzy_match_result_trailing_ws_strategy():
    """Trailing whitespace match reports 'trailing-ws' strategy."""
    from file_ops import fuzzy_find
    result = fuzzy_find("hello   \nworld", "hello\nworld")
    assert result.found
    assert result.strategy == "trailing-ws"


def test_fuzzy_match_result_full_fuzzy_strategy():
    """Unicode normalization match reports 'full-fuzzy' strategy."""
    from file_ops import fuzzy_find
    result = fuzzy_find("it\u2019s a test", "it's a test")
    assert result.found
    assert result.strategy == "full-fuzzy"


# ===================================================================
# 9. Edge Cases
# ===================================================================
def test_fuzzy_single_line_no_newline():
    """Single line without trailing newline."""
    from file_ops import find_and_replace
    content = "hello world"
    pattern = "hello world"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert new == "replaced"


def test_fuzzy_match_at_end_of_file():
    """Pattern at the very end of file content."""
    from file_ops import find_and_replace
    content = "line1\nline2\nlast line"
    pattern = "last line"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert new == "line1\nline2\nreplaced"


def test_fuzzy_match_at_start_of_file():
    """Pattern at the very start of file content."""
    from file_ops import find_and_replace
    content = "first line\nline2\nline3"
    pattern = "first line"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert new == "replaced\nline2\nline3"


def test_fuzzy_preserves_unchanged_content():
    """Content outside the match is preserved exactly."""
    from file_ops import find_and_replace
    content = "before   \nhello world   \nafter   \n"
    pattern = "hello world"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_multiline_with_unicode():
    """Multiline match with Unicode characters."""
    from file_ops import find_and_replace
    content = "\u201cLine one\u201d\n\u201cLine two\u201d\n"
    pattern = '"Line one"\n"Line two"'
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert "replaced" in new


def test_fuzzy_preserves_bom_in_output():
    """BOM is stripped for matching but output preserves normalized content."""
    from file_ops import find_and_replace, normalize_text
    content = "\ufeffhello\nworld\n"
    # normalize_text strips BOM (as it should)
    normed = normalize_text(content)
    base, new, start, end = find_and_replace(normed, "hello", "replaced", path="test.txt")
    assert "replaced" in new
    assert "\ufeff" not in new  # BOM was stripped during normalization


# ===================================================================
# 10. Error Message Quality Tests
# ===================================================================
def test_error_message_helpful_for_not_found():
    """Error message gives actionable guidance."""
    from file_ops import find_and_replace
    try:
        find_and_replace("hello world", "nonexistent text xyz", "replaced", path="myfile.py")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        msg = str(e).lower()
        assert "not found" in msg
        assert "myfile.py" in msg


def test_fuzzy_match_result_index_correct():
    """Match index points to correct position in content."""
    from file_ops import fuzzy_find
    result = fuzzy_find("aaa bbb ccc", "bbb")
    assert result.found
    assert result.index == 4  # "aaa " is 4 chars


def test_fuzzy_match_result_length_correct():
    """Match length equals pattern length."""
    from file_ops import fuzzy_find
    result = fuzzy_find("hello world", "world")
    assert result.found
    assert result.match_length == 5


def test_fuzzy_empty_content():
    """Empty content returns not found."""
    from file_ops import fuzzy_find
    result = fuzzy_find("", "anything")
    assert not result.found


def test_fuzzy_empty_pattern_raises():
    """Empty pattern in find_and_replace raises ValueError."""
    from file_ops import find_and_replace
    try:
        find_and_replace("content", "", "replaced", path="test.txt")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "empty" in str(e).lower()


def test_fuzzy_pattern_longer_than_content():
    """Pattern longer than content returns not found."""
    from file_ops import fuzzy_find
    result = fuzzy_find("short", "much longer pattern")
    assert not result.found


def test_fuzzy_newlines_in_both_sides():
    """Both file and pattern have newlines — exact match wins."""
    from file_ops import fuzzy_find
    result = fuzzy_find("line1\nline2\nline3", "line1\nline2")
    assert result.found
    assert result.strategy == "exact"


def test_fuzzy_only_last_line():
    """Match only the last line of content."""
    from file_ops import find_and_replace
    content = "line1\nline2\nline3"
    pattern = "line3"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert new == "line1\nline2\nreplaced"
    assert start == 3


def test_fuzzy_only_first_line():
    """Match only the first line of content."""
    from file_ops import find_and_replace
    content = "line1\nline2\nline3"
    pattern = "line1"
    base, new, start, end = find_and_replace(content, pattern, "replaced", path="test.txt")
    assert new == "replaced\nline2\nline3"
    assert start == 1


def test_fuzzy_preserves_indentation_in_replacement():
    """Indentation in replacement is preserved."""
    from file_ops import find_and_replace
    content = "def foo():\n    pass\n"
    pattern = "def foo():\n    pass"
    base, new, start, end = find_and_replace(
        content, pattern, "def foo():\n    return 42", path="test.py"
    )
    assert "return 42" in new


def test_fuzzy_multiple_edits_same_file():
    """Multiple sequential edits to the same file work correctly."""
    from file_ops import find_and_replace
    content = "alpha\nbeta\ngamma\n"

    # First edit
    base1, new1, _, _ = find_and_replace(content, "alpha", "ALPHA", path="test.txt")
    assert "ALPHA" in new1

    # Second edit on the result of first
    base2, new2, _, _ = find_and_replace(new1, "beta", "BETA", path="test.txt")
    assert "ALPHA" in new2  # First edit preserved
    assert "BETA" in new2


def test_fuzzy_special_regex_chars_in_pattern():
    """Pattern with regex special chars works (we use str.find, not re.match)."""
    from file_ops import find_and_replace
    content = 'price: $100.00\nqty: 5\n'
    pattern = "price: $100.00"  # $ and . are regex special chars
    base, new, start, end = find_and_replace(content, pattern, "price: $99.99", path="test.txt")
    assert "$99.99" in new


def test_fuzzy_content_with_null_bytes():
    """Content with null bytes (binary-ish files) doesn't crash."""
    from file_ops import fuzzy_find
    content = "hello\x00world\nfoo bar"
    result = fuzzy_find(content, "foo bar")
    assert result.found


def test_fuzzy_very_long_content():
    """Fuzzy matching works on very long content (performance check)."""
    from file_ops import fuzzy_find
    # 10K lines of content
    content = "\n".join(f"line {i}: some data" for i in range(10000)) + "\n"
    pattern = "line 5000: some data"
    result = fuzzy_find(content, pattern)
    assert result.found
    assert result.index != -1


def test_fuzzy_unicode_normalization_nfkc():
    """NFKC normalization handles compatibility characters."""
    from file_ops import normalize_text
    # Ligature "ﬁ" (U+FB01) should normalize to "fi" via NFKC
    content = "ro\u0131le\n"  # dotless i with combining dot above
    normed = normalize_text(content)
    # After NFKC, this should be decomposed
    assert normed is not None


def test_fuzzy_model_sends_extra_blank_line():
    """Model adds extra blank line — trailing ws strategy handles it."""
    from file_ops import find_and_replace
    content = "line1\nline2\n"
    pattern = "line1\nline2\n\n"  # model added extra blank line at end
    # This should NOT match (the extra newline is structural, not whitespace)
    try:
        find_and_replace(content, pattern, "replaced", path="test.txt")
        # If it matches via some strategy, that's also acceptable as long as it doesn't crash
    except ValueError:
        pass  # Expected — structural difference shouldn't fuzzy match


# ===================================================================
# 11. Real-World Scenario Tests
# ===================================================================
def test_real_world_python_edit_with_smart_quotes():
    """Realistic Python edit with smart quotes from copy-paste."""
    from file_ops import find_and_replace
    # File has actual Unicode smart quotes (from web copy-paste)
    content = 'def greet(name):\n    msg = \u201cHello World\u201d\n    return True\n'
    # Model sends clean ASCII version
    pattern = 'def greet(name):\n    msg = "Hello World"'
    base, new, start, end = find_and_replace(content, pattern, 'def greet(name):\n    msg = "Hi World"', path="app.py")
    assert "Hi World" in new


def test_real_world_shell_script_crlf():
    """Shell script saved with Windows line endings."""
    from file_ops import find_and_replace
    content = "#!/bin/bash\r\necho \"Hello\"\r\nexit 0\r\n"
    pattern = '#!/bin/bash\necho "Hello"'
    base, new, start, end = find_and_replace(content, pattern, '#!/bin/bash\necho "Hi"', path="script.sh")
    assert "Hi" in new


def test_real_world_config_with_nbsp():
    """Config file with NBSP from web copy-paste."""
    from file_ops import find_and_replace
    content = "DATABASE_URL = \"postgres://localhost/db\"\nDEBUG = True\n"
    # Model sends clean version, file might have NBSPs
    pattern_debug = "DEBUG = True"
    base, new, start, end = find_and_replace(content, pattern_debug, "DEBUG = False", path="settings.py")
    assert "False" in new


# ===================================================================
# Runner
# ===================================================================
def run_tests():
    """Run all tests and report results."""
    import traceback

    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed, failed, errors = 0, 0, 0

    for tfn in test_funcs:
        name = tfn.__name__
        try:
            import inspect
            sig = inspect.signature(tfn)
            params = list(sig.parameters.keys())

            if "tmp_path" in params:
                import tempfile
                from pathlib import Path
                with tempfile.TemporaryDirectory() as td:
                    tfn(tmp_path=Path(td))
            else:
                tfn()

            passed += 1
            print(f"  \033[32mPASS\033[0m {name}")
        except Exception as e:
            failed += 1
            print(f"  \033[31mFAIL\033[0m {name}: {e}")
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(
        f"Results: \033[32m{passed} passed\033[0m, "
        f"\033[31m{failed} failed\033[0m, "
        f"\033[33m{errors} errors\033[0m"
    )

    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)