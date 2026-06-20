"""Comprehensive tests for dual-limit truncation in shell_executor."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace")


# ===================================================================
# 1. No Truncation Needed (output fits within both limits)
# ===================================================================
def test_no_truncation_short_output():
    """Short output passes through unchanged."""
    from shell_executor import truncate_output
    text = "hello\nworld\n"
    result, truncated, tmp = truncate_output(text)
    assert not truncated
    assert tmp is None
    assert result == text


def test_no_truncation_exactly_at_line_limit():
    """Output exactly at line limit passes through."""
    from shell_executor import truncate_output
    lines = "\n".join(f"line {i}" for i in range(1000)) + "\n"
    result, truncated, tmp = truncate_output(lines)
    assert not truncated
    assert tmp is None


def test_no_truncation_exactly_at_byte_limit():
    """Output exactly at byte limit passes through."""
    from shell_executor import truncate_output
    # 64KB - 1 byte to leave room for the trailing newline
    text = "x" * (64 * 1024 - 1) + "\n"
    result, truncated, tmp = truncate_output(text)
    assert not truncated
    assert tmp is None


def test_no_truncation_empty_output():
    """Empty output passes through unchanged."""
    from shell_executor import truncate_output
    result, truncated, tmp = truncate_output("")
    assert not truncated
    assert tmp is None
    assert result == ""


# ===================================================================
# 2. Line Limit Truncation
# ===================================================================
def test_truncation_exceeds_lines():
    """Output exceeding line limit keeps tail."""
    from shell_executor import truncate_output
    lines = "\n".join(f"line {i}" for i in range(1500)) + "\n"
    result, truncated, tmp = truncate_output(lines)

    assert truncated
    assert tmp is not None
    assert os.path.exists(tmp)

    # Check header mentions line range
    assert "Showing lines 501-1500 of 1500" in result
    assert "Full output:" in result

    # Verify full output preserved in temp file
    full_content = Path(tmp).read_text()
    assert full_content == lines


def test_truncation_keeps_tail_not_head():
    """Truncation keeps the LAST N lines, not the first."""
    from shell_executor import truncate_output
    lines = "\n".join(f"line {i}" for i in range(2000)) + "\n"
    result, truncated, tmp = truncate_output(lines)

    assert truncated
    # Last line should be present
    assert "line 1999" in result
    # First line should NOT be present (it was truncated)
    assert "line 0" not in result


def test_truncation_many_lines():
    """Very large output is properly truncated."""
    from shell_executor import truncate_output
    lines = "\n".join(f"line {i}" for i in range(10000)) + "\n"
    result, truncated, tmp = truncate_output(lines)

    assert truncated
    assert "Showing lines 9001-10000 of 10000" in result


# ===================================================================
# 3. Byte Limit Truncation (wide output)
# ===================================================================
def test_truncation_single_huge_line():
    """Single line exceeding byte limit is truncated."""
    from shell_executor import truncate_output
    # 100KB single line (exceeds 64KB limit, but only 1 line)
    text = "x" * (100 * 1024) + "\n"
    result, truncated, tmp = truncate_output(text)

    assert truncated
    assert tmp is not None
    assert os.path.exists(tmp)

    # Header should mention bytes
    assert "bytes" in result.lower() or "truncated" in result.lower()


def test_truncation_wide_lines_few_count():
    """Few lines but very wide — byte limit triggers."""
    from shell_executor import truncate_output
    # 10 lines, each 10KB = 100KB total (exceeds 64KB, under 1000 lines)
    text = "\n".join("x" * (10 * 1024) for _ in range(10)) + "\n"
    result, truncated, tmp = truncate_output(text)

    assert truncated
    # Should keep tail lines that fit within byte budget
    assert "truncated" in result.lower() or "bytes" in result.lower()


def test_truncation_json_like_output():
    """Realistic scenario: single-line JSON dump exceeding byte limit."""
    from shell_executor import truncate_output
    # Simulate a large JSON response on one line — 10K entries to exceed 64KB
    entries = ','.join(f'{{"id": {i}, "name": "item_"}}' for i in range(10000))
    text = '{"data": [' + entries + ']}\n'
    result, truncated, tmp = truncate_output(text)

    assert truncated, f"Expected truncation for {len(text.encode('utf-8'))} bytes"
    assert tmp is not None


# ===================================================================
# 4. Both Limits Exceeded
# ===================================================================
def test_truncation_both_limits_exceeded():
    """Output exceeds both line AND byte limits — line limit takes priority."""
    from shell_executor import truncate_output
    # 2000 lines, each 100 bytes = 200KB total (exceeds both limits)
    text = "\n".join("x" * 100 for _ in range(2000)) + "\n"
    result, truncated, tmp = truncate_output(text)

    assert truncated
    # Line truncation takes priority when exceeded_lines is True
    assert "Showing lines" in result


def test_truncation_bytes_exceeded_first():
    """Byte limit hit before line limit (wide but few lines)."""
    from shell_executor import truncate_output
    # 100 lines, each 2KB = 200KB total (exceeds bytes, under lines)
    text = "\n".join("x" * 2048 for _ in range(100)) + "\n"
    result, truncated, tmp = truncate_output(text)

    assert truncated
    # Byte-based truncation header
    assert "bytes" in result.lower()


# ===================================================================
# 5. Custom Limits
# ===================================================================
def test_custom_line_limit():
    """Custom max_lines parameter works."""
    from shell_executor import truncate_output
    text = "\n".join(f"line {i}" for i in range(100)) + "\n"
    result, truncated, tmp = truncate_output(text, max_lines=50)

    assert truncated
    assert "Showing lines 51-100 of 100" in result


def test_custom_byte_limit():
    """Custom max_bytes parameter works."""
    from shell_executor import truncate_output
    text = "x" * 1000 + "\n"
    result, truncated, tmp = truncate_output(text, max_bytes=500)

    assert truncated


# ===================================================================
# 6. Edge Cases
# ===================================================================
def test_truncation_unicode_content():
    """Unicode content is handled correctly in byte counting."""
    from shell_executor import truncate_output
    # Each emoji is 4 bytes in UTF-8
    text = "\n".join("😀" * 100 for _ in range(50)) + "\n"
    result, truncated, tmp = truncate_output(text)

    # Should not crash, should handle multi-byte chars
    assert isinstance(result, str)


def test_truncation_mixed_line_endings():
    """Mixed line endings (CRLF/LF) handled gracefully."""
    from shell_executor import truncate_output
    text = "line1\r\nline2\nline3\r\n"
    result, truncated, tmp = truncate_output(text)

    # Should not crash
    assert isinstance(result, str)


def test_truncation_only_newlines():
    """Output that's only newlines."""
    from shell_executor import truncate_output
    text = "\n" * 2000
    result, truncated, tmp = truncate_output(text)

    assert truncated
    assert isinstance(result, str)


def test_truncation_no_trailing_newline():
    """Output without trailing newline."""
    from shell_executor import truncate_output
    text = "\n".join(f"line {i}" for i in range(1500))  # no trailing \n
    result, truncated, tmp = truncate_output(text)

    assert truncated
    assert "line 1499" in result


def test_truncation_temp_file_readable():
    """Temp file contains the full original output."""
    from shell_executor import truncate_output
    original = "\n".join(f"line {i}" for i in range(2000)) + "\n"
    result, truncated, tmp = truncate_output(original)

    assert truncated
    assert tmp is not None
    full_content = Path(tmp).read_text(encoding="utf-8")
    assert full_content == original


def test_truncation_preserves_special_chars():
    """Special characters in output are preserved."""
    from shell_executor import truncate_output
    text = "hello $WORLD\n`cmd`\npath/to/file\n100%\n"
    result, truncated, tmp = truncate_output(text)

    assert not truncated  # short output, no truncation needed
    assert "$WORLD" in result
    assert "`cmd`" in result


# ===================================================================
# 7. Integration with execute_shell_action (smoke test)
# ===================================================================
def test_truncation_constant_values():
    """Constants have reasonable default values."""
    from shell_executor import SHELL_MAX_LINES, SHELL_MAX_BYTES

    assert SHELL_MAX_LINES == 1000
    assert SHELL_MAX_BYTES == 64 * 1024


def test_truncation_result_format():
    """Truncated result has proper format for LLM consumption."""
    from shell_executor import truncate_output
    text = "\n".join(f"line {i}" for i in range(1500)) + "\n"
    result, truncated, tmp = truncate_output(text)

    assert truncated
    # Format: "...\\n[metadata]\\nactual_content"
    assert result.startswith("...\n")
    assert "[" in result  # metadata header
    assert "]" in result


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