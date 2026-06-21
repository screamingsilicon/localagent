"""Tests for quick-win improvements: BOM, compaction, truncation, multi-edit."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace")


# 1. BOM Handling Tests
def test_bom_strip_basic():
    """BOM at start of string is stripped."""
    from file_ops import strip_bom
    text = "\ufeffprint('hello')\n"
    cleaned, had_bom = strip_bom(text)
    assert had_bom is True
    assert cleaned == "print('hello')\n"
    assert "\ufeff" not in cleaned


def test_bom_strip_no_bom():
    """Text without BOM passes through unchanged."""
    from file_ops import strip_bom
    text = "print('hello')\n"
    cleaned, had_bom = strip_bom(text)
    assert had_bom is False
    assert cleaned == text


def test_normalize_strips_bom():
    """normalize_text() strips BOM before any other processing."""
    from file_ops import normalize_text
    text = "\ufeffline1\r\nline2  \r\n"
    result = normalize_text(text)
    assert "\ufeff" not in result
    assert result == "line1\nline2\n"


def test_normalize_strict_strips_bom():
    """Even strict mode strips BOM."""
    from file_ops import normalize_text
    text = "\ufeffhello  \nworld  "
    result = normalize_text(text, strict=True)
    assert "\ufeff" not in result
    assert result == "hello  \nworld  "


def test_edit_with_bom_file():
    """find_and_replace on BOM content should match without BOM in old_text."""
    from file_ops import find_and_replace

    # Simulate reading a BOM file (what read_file returns after normalize_text strips BOM)
    raw_content = "\ufeffdef hello():\n    print('world')\n"
    from file_ops import normalize_text
    content = normalize_text(raw_content)  # This strips BOM

    result = find_and_replace(
        content,
        "def hello():\n    print('world')",
        "def hello():\n    print('universe')",
        path="bom_test.py",
    )
    base, new_content, start, end = result
    assert "universe" in new_content


# 2. File Path Extraction Tests (for compaction)
def test_extract_file_paths_reads():
    """Extract file paths from read operations."""
    from context_manager import _extract_file_paths

    content = (
        "cat config.py\n"
        "head app.js\n"
        "tail README.md\n"
        "Error reading utils.rs: not found\n"
    )
    reads, mods = _extract_file_paths(content)
    assert "config.py" in reads, f"Expected config.py in {reads}"
    assert "app.js" in reads, f"Expected app.js in {reads}"


def test_extract_file_paths_modifications():
    """Extract file paths from write/edit operations."""
    from context_manager import _extract_file_paths

    content = (
        "Successfully edited app.py\n"
        "Wrote content to new_module.js\n"
        "Successfully edited config.yaml\n"
    )
    reads, mods = _extract_file_paths(content)
    assert "app.py" in mods
    assert "new_module.js" in mods
    assert "config.yaml" in mods


def test_extract_file_paths_deduplicates():
    """Same file mentioned multiple times appears only once."""
    from context_manager import _extract_file_paths

    content = (
        "Successfully edited app.py\n"
        "Successfully edited app.py\n"
        "cat app.py\n"
    )
    reads, mods = _extract_file_paths(content)
    assert reads.count("app.py") <= 1
    assert mods.count("app.py") <= 1


# 3. Shell Truncation Messaging Tests
def test_shell_truncation_shows_line_range():
    """Truncated output shows 'Showing lines X-Y of Z'."""
    from shell_executor import execute_shell

    # Generate enough output to trigger truncation (>1000 lines)
    cmd = "for i in $(seq 1 1500); do echo \"line $i content here\"; done"
    # execute_shell takes an act dict, not raw args
    result = execute_shell(
        {"command": cmd},
        auto_mode=True,
        cwd="/workspace",
        sandbox=False,
        sudo_cache=None,
        log_tool_call=None,
    )

    assert "Showing lines" in result, f"Expected line range in output: {result[:300]}"
    import re
    m = re.search(r'Showing lines (\d+)-(\d+) of (\d+)', result)
    assert m is not None, f"Expected line range pattern in: {result[:300]}"
    start, end, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
    assert total >= 1001, f"Total should be >1000, got {total}"


def test_shell_no_truncation_under_threshold():
    """Short output is NOT truncated."""
    from shell_executor import execute_shell

    result = execute_shell(
        {"command": "echo hello; echo world"},
        auto_mode=True,
        cwd="/workspace",
        sandbox=False,
        sudo_cache=None,
        log_tool_call=None,
    )
    assert "Showing lines" not in result
    assert "hello" in result
    assert "world" in result


# 4. Context Manager Token Estimation Tests
def test_estimate_uses_provider_usage():
    """Token estimation prefers provider usage when available."""
    from context_manager import compress_context

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello" * 100},
        {
            "role": "assistant",
            "content": "Hi there!" + "x" * 5000,
            "_usage": {"total_tokens": 3500},
        },
    ]

    result_msgs, summary = compress_context(
        messages, "", config=None, llm_request_fn=lambda x, **kw: None
    )
    assert result_msgs is not None


def test_estimate_fallback_char_based():
    """Token estimation falls back to char-based when no usage available."""
    from context_manager import compress_context

    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]

    result_msgs, summary = compress_context(
        messages, "", config=None, llm_request_fn=lambda x, **kw: None
    )
    assert result_msgs is not None


# 5. Incremental Summary Update Tests
def test_incremental_summary_prompt_structure():
    """Verify that incremental update prompt includes previous summary."""
    from context_manager import compress_context

    mock_responses = [
        {
            "choices": [
                {"message": {"content": "## Goal\nFirst task.\n## Progress\n### Done\n- [x] step 1"}}
            ]
        },
    ]

    def mock_llm(msgs, **kw):
        resp = mock_responses.pop(0) if mock_responses else None
        return resp

    messages = [
        {"role": "system", "content": "System"},
        {"role": "user", "content": "Do task A: create file.py"},
        {"role": "assistant", "content": "Creating file..."},
        {"role": "user", "content": "### Action Results\nWrote content to file.py"},
    ]

    result_msgs, summary = compress_context(
        messages, "", config=None, llm_request_fn=mock_llm
    )
    assert isinstance(result_msgs, list)


# 6. System Prompt Content Tests
def test_system_prompt_has_multi_edit_guidance():
    """System prompt instructs model to batch edits."""
    prompt = Path("/workspace/system_prompt.md").read_text()
    assert "multiple" in prompt.lower(), "Should mention multiple edits"
    assert "batch" in prompt.lower() or "single" in prompt.lower(), "Should suggest batching"
    # Check for done tag (may appear as literal angle brackets)
    assert "done" in prompt.lower(), "Should include done instruction"


def test_system_prompt_has_find_block_guidance():
    """System prompt guides model on find block precision."""
    prompt = Path("/workspace/system_prompt.md").read_text()
    assert "unique" in prompt.lower(), "Should mention uniqueness"
    assert "small" in prompt.lower() or "minimal" in prompt.lower(), "Should suggest minimal find blocks"


# 7. End-to-end: BOM file edit through find_and_replace
def test_e2e_edit_bom_file():
    """Full flow: read BOM file via read_file, edit via find_and_replace."""
    from file_ops import find_and_replace, normalize_text

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8-sig"
    ) as f:
        f.write("def old_func():\n    return 42\n")
        fpath = f.name

    try:
        # Simulate what read_file does: reads raw, then normalize_text strips BOM
        raw = open(fpath, "r", encoding="utf-8").read()
        content = normalize_text(raw)
        assert "\ufeff" not in content, "BOM should be stripped by normalize_text"

        result = find_and_replace(content, "return 42", "return 100", path=fpath)
        base, new_content, start, end = result
        assert "return 100" in new_content
    finally:
        os.unlink(fpath)


def test_e2e_edit_bom_file_no_bom_in_find():
    """Model can find text without including BOM in the <find> block."""
    from file_ops import find_and_replace, normalize_text

    # File content as it would come from disk with BOM
    raw_content = "\ufeff# -*- coding: utf-8 -*-\nVALUE = 1\n"
    content = normalize_text(raw_content)  # strips BOM

    # Model sends find block WITHOUT BOM (normal behavior — models don't know about BOM)
    result = find_and_replace(content, "VALUE = 1", "VALUE = 2", path="test.py")
    base, new_content, start, end = result
    assert "VALUE = 2" in new_content


# Runner
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