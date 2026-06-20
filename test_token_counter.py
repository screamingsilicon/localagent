"""Comprehensive tests for the pure-Python token counter.

Tests cover:
  - Known cl100k_base token counts (from published OpenAI examples)
  - Common English prose at various lengths
  - Code snippets (Python, Bash, HTML/XML)
  - CJK text (Chinese, Japanese, Korean)
  - Mixed scripts and emoji
  - URLs, emails, hex hashes
  - Edge cases (empty, whitespace, special chars, very long strings)
  - Comparison with the legacy //4 estimator
  - Performance benchmarks
  - Message-list estimation
"""

from __future__ import annotations

import sys
import time
import textwrap
from token_counter import (
    count_tokens,
    count_tokens_messages,
    _rough_estimate,
)


def test_empty_and_whitespace():
    """Edge cases: empty strings and whitespace-only input."""
    assert count_tokens("") == 0, f"empty string should be 0, got {count_tokens('')}"
    assert count_tokens("   ") == 0, f"whitespace-only should be 0, got {count_tokens('   ')}"
    assert count_tokens("\n\n\t") == 0, f"newlines/tabs should be 0, got {count_tokens(chr(10)*2+chr(9))}"
    assert count_tokens("hello") > 0, "non-empty string should be > 0"


def test_single_common_words():
    """Common English words should each be ~1 token."""
    common = ["the", "and", "for", "with", "from", "this", "that", "have", "been", "will"]
    for word in common:
        tokens = count_tokens(word)
        assert tokens == 1, f"'{word}' should be ~1 token, got {tokens}"


def test_single_uncommon_words():
    """Uncommon/longer words may be 1-2 tokens."""
    # Short uncommon words are typically still 1 token
    assert count_tokens("xyz") <= 2, f"short uncommon word 'xyz' should be ≤2 tokens, got {count_tokens('xyz')}"
    # Longer uncommon words get split
    assert count_tokens("antidisestablishmentarianism") >= 3, \
        f"very long word should be ≥3 tokens, got {count_tokens('antidisestablishmentarianism')}"


def test_short_sentences():
    """Short English sentences — verify reasonable estimates."""
    # "Hello world" ≈ 2 tokens in cl100k_base
    t = count_tokens("Hello world")
    assert 1 <= t <= 3, f"'Hello world' should be ~2 tokens, got {t}"

    # "The quick brown fox jumps over the lazy dog." ≈ 9-10 tokens
    t = count_tokens("The quick brown fox jumps over the lazy dog.")
    assert 6 <= t <= 13, f"'quick brown fox' sentence should be ~9-10 tokens, got {t}"

    # "I love programming" ≈ 3-4 tokens
    t = count_tokens("I love programming")
    assert 2 <= t <= 5, f"'I love programming' should be ~3-4 tokens, got {t}"


def test_paragraph():
    """A full paragraph of English prose."""
    text = (
        "Natural language processing is a subfield of linguistics, computer science, "
        "and artificial intelligence concerned with the interactions between computers "
        "and human language, in particular how to program computers to process and "
        "analyze large amounts of natural language data."
    )
    t = count_tokens(text)
    rough = _rough_estimate(text)
    # The paragraph is ~320 chars; //4 gives 80
    # Real cl100k_base ≈ 55-65 tokens for this text
    assert 40 <= t <= 75, f"paragraph should be ~55-65 tokens, got {t}"
    # Our estimate should be in a reasonable ballpark vs //4
    print(f"  Paragraph: chars={len(text)}, //4={rough}, ours={t}")


def test_python_code():
    """Python code snippets."""
    code = textwrap.dedent("""\
        def fibonacci(n: int) -> list[int]:
            result = []
            a, b = 0, 1
            for _ in range(n):
                result.append(a)
                a, b = b, a + b
            return result
    """)
    t = count_tokens(code)
    # ~70 chars of code; real ≈ 45-55 tokens
    assert 30 <= t <= 70, f"fibonacci function should be ~45-55 tokens, got {t}"

    # Single line
    t2 = count_tokens("x = foo_bar_baz(my_variable)")
    assert 5 <= t2 <= 12, f"'x = foo_bar_baz(my_variable)' should be ~7-9 tokens, got {t2}"


def test_bash_code():
    """Bash/shell commands."""
    t = count_tokens("git commit -m 'fix: resolve auth bug'")
    assert 5 <= t <= 12, f"git commit command should be ~6-10 tokens, got {t}"

    t2 = count_tokens("docker run --name agent-sandbox -d python:3.12-alpine tail -f /dev/null")
    assert 8 <= t2 <= 18, f"docker run command should be ~10-15 tokens, got {t2}"


def test_xml_tags():
    """XML/HTML tags as used by the agent."""
    # Simple tag
    t = count_tokens("<shell>ls -la</shell>")
    assert 4 <= t <= 10, f"<shell> tag should be ~5-8 tokens, got {t}"

    # Tag with attributes
    t2 = count_tokens('<edit path="file.py">\n<find>old</find>\n<replace>new</replace>\n</edit>')
    assert 8 <= t2 <= 18, f"edit tag with attrs should be ~10-15 tokens, got {t2}"

    # HTML
    t3 = count_tokens("<div class='container'><p>Hello</p></div>")
    assert 5 <= t3 <= 12, f"HTML div/p should be ~6-10 tokens, got {t3}"


def test_urls():
    """URLs tokenize efficiently."""
    t = count_tokens("https://example.com/path/to/resource")
    assert 2 <= t <= 5, f"simple URL should be ~3-4 tokens, got {t}"

    t2 = count_tokens("https://github.com/user/repo/blob/main/src/file.py#L10-L20")
    assert 4 <= t2 <= 9, f"GitHub URL should be ~5-7 tokens, got {t2}"


def test_emails():
    """Email addresses."""
    t = count_tokens("user@example.com")
    assert 1 <= t <= 3, f"email should be ~2 tokens, got {t}"


def test_numbers():
    """Numbers at various scales."""
    # Short number → 1 token
    assert count_tokens("42") == 1, f"'42' should be 1 token, got {count_tokens('42')}"
    assert count_tokens("3.14159") <= 2, f"'3.14159' should be ≤2 tokens, got {count_tokens('3.14159')}"

    # Long number → split by ~4 digits
    t = count_tokens("12345678901234567890")
    assert 3 <= t <= 6, f"long number should be ~5 tokens, got {t}"


def test_cjk_chinese():
    """Chinese characters."""
    # Each CJK char ≈ 1 token for common chars; "你好世界" (4 chars) ≈ 4-5 tokens
    t = count_tokens("你好世界")
    assert 3 <= t <= 6, f"'你好世界' (4 CJK chars) should be ~4-5 tokens, got {t}"

    # Longer Chinese text (~27 chars) ≈ 27-35 tokens (common chars mostly single tokens)
    t2 = count_tokens("人工智能是计算机科学的一个分支，它致力于创造能够执行智能任务的系统")
    assert 20 <= t2 <= 40, f"longer Chinese text should be ~27-35 tokens, got {t2}"


def test_cjk_japanese():
    """Japanese (mix of kanji, hiragana, katakana)."""
    # "こんにちは世界" ≈ 6-10 tokens
    t = count_tokens("こんにちは世界")
    assert 5 <= t <= 12, f"'こんにちは世界' should be ~7-9 tokens, got {t}"


def test_cjk_korean():
    """Korean Hangul."""
    t = count_tokens("안녕하세요 세계")
    assert 4 <= t <= 10, f"'안녕하세요 세계' should be ~5-8 tokens, got {t}"


def test_emoji():
    """Emoji clusters (each ≈ 2 tokens)."""
    t = count_tokens("🎉🚀💻")
    assert 3 <= t <= 6, f"3 emoji should be ~6 tokens, got {t}"

    # Mixed text with emoji
    t2 = count_tokens("Hello world 🎉 great!")
    assert 4 <= t2 <= 8, f"text with emoji should be ~5-7 tokens, got {t2}"


def test_mixed_scripts():
    """Text mixing multiple scripts."""
    t = count_tokens("Hello 世界 🎉你好 world")
    assert 6 <= t <= 14, f"mixed scripts should be ~8-12 tokens, got {t}"


def test_hex_colors_and_hashes():
    """Hex color codes and hash strings."""
    t = count_tokens("#ff00aa")
    assert 1 <= t <= 3, f"hex color should be ~1-2 tokens, got {t}"

    # SHA256-like hash (40 hex chars → matched by bare hex regex)
    h = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
    t2 = count_tokens(h)
    assert 3 <= t2 <= 8, f"SHA-like hash should be ~4-6 tokens, got {t2}"


def test_punctuation_heavy():
    """Text with lots of punctuation."""
    t = count_tokens("What??? Really?! No way... Seriously??")
    assert 5 <= t <= 10, f"punctuation-heavy text should be ~6-8 tokens, got {t}"


def test_very_long_text():
    """A very long text — verify it scales linearly and doesn't crash."""
    # ~10,000 chars of repeated English prose
    sentence = "The quick brown fox jumps over the lazy dog. "
    long_text = (sentence * 350).strip()
    t = count_tokens(long_text)

    # Should be roughly proportional to length
    single_t = count_tokens(sentence.strip())
    expected_approx = single_t * 350
    assert 0.7 * expected_approx <= t <= 1.3 * expected_approx, \
        f"long text ({t}) should scale linearly from single sentence ({single_t} × 350 ≈ {expected_approx})"


def test_consistency():
    """Same input always produces the same output."""
    samples = [
        "Hello world",
        "def foo(): pass",
        "你好世界 🎉",
        "https://example.com/path",
        "The quick brown fox jumps over the lazy dog.",
    ]
    for text in samples:
        results = {count_tokens(text) for _ in range(10)}
        assert len(results) == 1, f"inconsistent results for '{text[:30]}': {results}"


def test_message_list():
    """Token estimation for a message list (with per-message overhead)."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, can you help me?"},
        {"role": "assistant", "content": "Of course! What do you need help with?"},
    ]
    total = count_tokens_messages(messages)

    # Sum of individual + overhead (4 tokens × 3 messages)
    sum_individual = sum(count_tokens(m["content"]) for m in messages)
    assert total == sum_individual + 12, \
        f"message list total ({total}) should be sum ({sum_individual}) + 12 overhead"


def test_comparison_with_legacy():
    """Our estimator should be more reasonable than //4 for most real text."""
    samples = [
        ("Hello world", "short English"),
        ("The quick brown fox jumps over the lazy dog.", "medium sentence"),
        ("def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a", "Python code"),
        ("<shell>git log --oneline -5</shell>", "XML tool tag"),
        ("你好世界 人工智能是计算机科学的一个分支", "CJK text"),
        ("https://github.com/user/repo/blob/main/src/file.py#L10-L20", "URL"),
    ]

    for text, label in samples:
        ours = count_tokens(text)
        legacy = _rough_estimate(text)
        chars = len(text)
        print(f"  {label}: chars={chars}, //4={legacy}, ours={ours}")

    # Key assertion: our estimator handles CJK much better than //4
    cjk_text = "你好世界 人工智能是计算机科学的一个分支"
    cjk_ours = count_tokens(cjk_text)
    cjk_legacy = _rough_estimate(cjk_text)
    assert cjk_ours > cjk_legacy * 3, \
        f"CJK: our estimate ({cjk_ours}) should be much higher than //4 ({cjk_legacy})"

    # Our estimator produces non-trivial results for all samples
    for text, label in samples:
        ours = count_tokens(text)
        assert ours >= 1, f"{label}: estimate should be ≥1, got {ours}"


def test_performance():
    """Estimate should be fast — sub-millisecond for typical inputs."""
    # Typical agent turn content (~5KB)
    typical = "Here is some code:\n\ndef example_function(x: int, y: str) -> bool:\n    if x > 0 and y.startswith('test'):\n        return True\n    return False\n\n# End of code\n\nThe output was successful. Next steps include testing edge cases." * 5

    iterations = 100
    start = time.monotonic()
    for _ in range(iterations):
        count_tokens(typical)
    elapsed = (time.monotonic() - start) / iterations * 1000  # ms per call

    print(f"  Performance: {elapsed:.2f}ms per estimation ({len(typical)} chars)")
    assert elapsed < 50, f"estimation should be fast (<50ms), got {elapsed:.2f}ms"


def test_performance_vs_legacy():
    """Our estimator should be fast enough for practical use."""
    text = "The quick brown fox jumps over the lazy dog. " * 100

    start = time.monotonic()
    for _ in range(1000):
        count_tokens(text)
    ours_ms = (time.monotonic() - start) / 1000 * 1000

    print(f"  Ours: {ours_ms:.3f}ms per call ({len(text)} chars)")
    # Should be fast enough for practical use (<15ms per typical input)
    assert ours_ms < 15.0, \
        f"our estimator ({ours_ms:.3f}ms) should complete in <15ms"


def test_special_characters():
    """Various special characters and Unicode."""
    # Tab/newline heavy
    t = count_tokens("a\nb\nc\nd\ne")
    assert 3 <= t <= 8, f"newline-separated should be ~5-6 tokens, got {t}"

    # Tabs
    t2 = count_tokens("col1\tcol2\tcol3")
    assert 3 <= t2 <= 7, f"tab-separated should be ~4-5 tokens, got {t2}"

    # Unicode normalization edge case — smart quotes
    t3 = count_tokens("'Hello'")
    t4 = count_tokens("ʻHelloʻ")  # different quote chars
    assert abs(t3 - t4) <= 1, f"similar quotes should give similar estimates: {t3} vs {t4}"


def test_known_patterns():
    """Patterns with well-known cl100k_base token counts (from published examples)."""
    # "Hello world!" is exactly 3 tokens in cl100k_base
    t = count_tokens("Hello world!")
    assert 2 <= t <= 4, f"'Hello world!' should be ~3 tokens, got {t}"

    # Single common word with space suffix: "the " ≈ 1 token (space merged)
    t2 = count_tokens("the")
    assert t2 == 1, f"'the' should be 1 token, got {t2}"

    # Number in text: "I have 42 apples" ≈ 4 tokens
    t3 = count_tokens("I have 42 apples")
    assert 3 <= t3 <= 6, f"'I have 42 apples' should be ~4 tokens, got {t3}"


def test_code_identifiers():
    """Code identifiers with various naming conventions."""
    # snake_case: often splits at underscores
    t = count_tokens("my_very_long_variable_name")
    assert 3 <= t <= 8, f"snake_case identifier should be ~4-6 tokens, got {t}"

    # camelCase: may split at boundaries
    t2 = count_tokens("myVariableName")
    assert 1 <= t2 <= 4, f"camelCase identifier should be ~2-3 tokens, got {t2}"

    # PascalCase
    t3 = count_tokens("MyClassName")
    assert 1 <= t3 <= 4, f"PascalCase identifier should be ~2-3 tokens, got {t3}"


def test_contraction_handling():
    """Contractions and apostrophes."""
    contractions = ["don't", "can't", "I'm", "you're", "they'll", "won't"]
    for c in contractions:
        t = count_tokens(c)
        # Contractions are typically 1-2 tokens in cl100k_base
        assert 1 <= t <= 3, f"contraction '{c}' should be ~1-2 tokens, got {t}"


def test_multiline_string():
    """Multi-line strings (common in code and prompts)."""
    text = """\
Here is a multi-line string:
Line one
Line two
Line three

With an empty line above."""
    t = count_tokens(text)
    assert 10 <= t <= 25, f"multiline string should be ~12-20 tokens, got {t}"


def test_repetitive_patterns():
    """Repetitive text patterns (like log output)."""
    # Repeated identical lines
    line = "INFO:root:Processing item 42\n"
    repeated = line * 50
    t = count_tokens(repeated)

    single_line_t = count_tokens(line.strip())
    expected_approx = single_line_t * 50
    assert 0.5 * expected_approx <= t <= 1.5 * expected_approx, \
        f"repeated lines ({t}) should scale from single line ({single_line_t} × 50 ≈ {expected_approx})"


def run_all():
    """Run all tests and report results."""
    tests = [
        test_empty_and_whitespace,
        test_single_common_words,
        test_single_uncommon_words,
        test_short_sentences,
        test_paragraph,
        test_python_code,
        test_bash_code,
        test_xml_tags,
        test_urls,
        test_emails,
        test_numbers,
        test_cjk_chinese,
        test_cjk_japanese,
        test_cjk_korean,
        test_emoji,
        test_mixed_scripts,
        test_hex_colors_and_hashes,
        test_punctuation_heavy,
        test_very_long_text,
        test_consistency,
        test_message_list,
        test_comparison_with_legacy,
        test_performance,
        test_performance_vs_legacy,
        test_special_characters,
        test_known_patterns,
        test_code_identifiers,
        test_contraction_handling,
        test_multiline_string,
        test_repetitive_patterns,
    ]

    passed = 0
    failed = 0
    errors = []

    for test_fn in tests:
        name = test_fn.__name__
        try:
            test_fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
            errors.append((name, str(e)))
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            failed += 1
            errors.append((name, f"{type(e).__name__}: {e}"))

    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")

    if errors:
        print("\nFailures:")
        for name, error in errors:
            print(f"  - {name}: {error}")
        sys.exit(1)
    else:
        print("All tests passed!")
        return True


if __name__ == "__main__":
    run_all()