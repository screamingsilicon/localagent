"""Tests for token_counter module — pure-Python token estimation."""

from __future__ import annotations

import time
import unittest
import textwrap

from token_counter import (
    count_tokens,
    count_tokens_messages,
    _rough_estimate,
)


class TestEmptyAndWhitespace(unittest.TestCase):
    """Edge cases: empty strings and whitespace-only input."""

    def test_empty_string(self):
        self.assertEqual(count_tokens(""), 0)

    def test_spaces_only(self):
        self.assertEqual(count_tokens("   "), 0)

    def test_newlines_and_tabs(self):
        self.assertEqual(count_tokens("\n\n\t"), 0)

    def test_non_empty_positive(self):
        self.assertGreater(count_tokens("hello"), 0)


class TestSingleWords(unittest.TestCase):
    """Word-level tokenization."""

    def test_common_words_one_token(self):
        common = ["the", "and", "for", "with", "from", "this", "that", "have", "been", "will"]
        for word in common:
            self.assertEqual(count_tokens(word), 1, f"'{word}' should be 1 token")

    def test_short_uncommon_word(self):
        self.assertLessEqual(count_tokens("xyz"), 2)

    def test_very_long_word_splitted(self):
        self.assertGreaterEqual(count_tokens("antidisestablishmentarianism"), 3)


class TestSentences(unittest.TestCase):
    """Short English sentences — verify reasonable estimates."""

    def test_hello_world(self):
        self.assertIn(count_tokens("Hello world"), range(1, 4))

    def test_pangram(self):
        self.assertIn(count_tokens("The quick brown fox jumps over the lazy dog."), range(6, 14))

    def test_i_love_programming(self):
        self.assertIn(count_tokens("I love programming"), range(2, 6))


class TestParagraph(unittest.TestCase):
    """A full paragraph of English prose."""

    def test_paragraph_range(self):
        text = (
            "Natural language processing is a subfield of linguistics, computer science, "
            "and artificial intelligence concerned with the interactions between computers "
            "and human language, in particular how to program computers to process and "
            "analyze large amounts of natural language data."
        )
        t = count_tokens(text)
        self.assertIn(t, range(40, 76), f"paragraph should be ~55-65 tokens, got {t}")

    def test_rough_estimate_reasonable(self):
        text = "The quick brown fox jumps over the lazy dog." * 10
        rough = _rough_estimate(text)
        self.assertGreater(rough, 0)


class TestCodeSnippets(unittest.TestCase):
    """Code snippets (Python, Bash, HTML/XML)."""

    def test_python_fibonacci(self):
        code = textwrap.dedent("""\
            def fibonacci(n: int) -> list[int]:
                result = []
                a, b = 0, 1
                for _ in range(n):
                    result.append(a)
                    a, b = b, a + b
                return result
        """)
        self.assertIn(count_tokens(code), range(30, 71))

    def test_single_line_python(self):
        self.assertIn(count_tokens("x = foo_bar_baz(my_variable)"), range(5, 13))

    def test_git_command(self):
        self.assertIn(count_tokens("git commit -m 'fix: resolve auth bug'"), range(5, 13))

    def test_docker_run_command(self):
        self.assertIn(
            count_tokens("docker run --name agent-sandbox -d python:3.12-alpine tail -f /dev/null"),
            range(8, 19),
        )


class TestXmlTags(unittest.TestCase):
    """XML/HTML tags as used by the agent."""

    def test_shell_tag(self):
        self.assertIn(count_tokens("<shell>ls -la</shell>"), range(4, 11))

    def test_edit_tag(self):
        self.assertIn(
            count_tokens('<edit path="file.py">\n<find>old</find>\n<replace>new</replace>\n</edit>'),
            range(8, 19),
        )

    def test_html_div(self):
        self.assertIn(count_tokens("<div class='container'><p>Hello</p></div>"), range(5, 13))


class TestUrlsAndEmails(unittest.TestCase):
    """URLs and email addresses."""

    def test_simple_url(self):
        self.assertIn(count_tokens("https://example.com/path/to/resource"), range(2, 6))

    def test_github_url(self):
        self.assertIn(
            count_tokens("https://github.com/user/repo/blob/main/src/file.py#L10-L20"),
            range(4, 10),
        )

    def test_email(self):
        self.assertIn(count_tokens("user@example.com"), range(1, 4))


class TestNumbers(unittest.TestCase):
    """Numbers at various scales."""

    def test_short_number(self):
        self.assertEqual(count_tokens("42"), 1)

    def test_float(self):
        self.assertLessEqual(count_tokens("3.14159"), 2)

    def test_long_number(self):
        self.assertIn(count_tokens("12345678901234567890"), range(3, 7))


class TestCjkText(unittest.TestCase):
    """CJK text (Chinese, Japanese, Korean)."""

    def test_chinese_chars(self):
        self.assertIn(count_tokens("你好世界"), range(3, 7))

    def test_longer_chinese(self):
        self.assertIn(
            count_tokens("人工智能是计算机科学的一个分支，它致力于创造能够执行智能任务的系统"),
            range(20, 41),
        )

    def test_japanese(self):
        self.assertIn(count_tokens("こんにちは世界"), range(5, 13))

    def test_korean(self):
        self.assertIn(count_tokens("안녕하세요 세계"), range(4, 11))


class TestEmoji(unittest.TestCase):
    """Emoji clusters."""

    def test_emoji_cluster(self):
        self.assertIn(count_tokens("🎉🚀💻"), range(3, 7))

    def test_text_with_emoji(self):
        self.assertIn(count_tokens("Hello world 🎉 great!"), range(4, 9))


class TestMixedScripts(unittest.TestCase):
    """Text mixing multiple scripts."""

    def test_mixed(self):
        self.assertIn(count_tokens("Hello 世界 🎉你好 world"), range(6, 15))


class TestHexAndHashes(unittest.TestCase):
    """Hex color codes and hash strings."""

    def test_hex_color(self):
        self.assertIn(count_tokens("#ff00aa"), range(1, 4))

    def test_sha_like_hash(self):
        h = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        self.assertIn(count_tokens(h), range(3, 9))


class TestPunctuation(unittest.TestCase):
    """Text with lots of punctuation."""

    def test_punctuation_heavy(self):
        self.assertIn(count_tokens("What??? Really?! No way... Seriously??"), range(5, 11))


class TestLongText(unittest.TestCase):
    """Very long text — verify linear scaling."""

    def test_very_long_scales_linearly(self):
        sentence = "The quick brown fox jumps over the lazy dog. "
        long_text = (sentence * 350).strip()
        t = count_tokens(long_text)
        single_t = count_tokens(sentence.strip())
        expected = single_t * 350
        self.assertGreaterEqual(t, 0.7 * expected)
        self.assertLessEqual(t, 1.3 * expected)


class TestConsistency(unittest.TestCase):
    """Same input always produces the same output."""

    def test_consistent_results(self):
        samples = [
            "Hello world",
            "def foo(): pass",
            "你好世界 🎉",
            "https://example.com/path",
            "The quick brown fox jumps over the lazy dog.",
        ]
        for text in samples:
            results = {count_tokens(text) for _ in range(10)}
            self.assertEqual(len(results), 1, f"inconsistent: {results}")


class TestMessageList(unittest.TestCase):
    """Token estimation for a message list."""

    def test_message_list_overhead(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, can you help me?"},
            {"role": "assistant", "content": "Of course! What do you need help with?"},
        ]
        total = count_tokens_messages(messages)
        sum_individual = sum(count_tokens(m["content"]) for m in messages)
        self.assertEqual(total, sum_individual + 12)


class TestComparisonWithLegacy(unittest.TestCase):
    """Our estimator vs the legacy //4 estimator."""

    def test_cjk_better_than_legacy(self):
        cjk_text = "你好世界 人工智能是计算机科学的一个分支"
        cjk_ours = count_tokens(cjk_text)
        cjk_legacy = _rough_estimate(cjk_text)
        self.assertGreater(cjk_ours, cjk_legacy * 3)

    def test_all_samples_positive(self):
        samples = [
            "Hello world",
            "def fibonacci(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a",
            "<shell>git log --oneline -5</shell>",
            "你好世界 人工智能是计算机科学的一个分支",
            "https://github.com/user/repo/blob/main/src/file.py#L10-L20",
        ]
        for text in samples:
            self.assertGreaterEqual(count_tokens(text), 1)


class TestPerformance(unittest.TestCase):
    """Estimation should be fast."""

    def test_typical_input_fast(self):
        typical = "def example(x: int, y: str) -> bool:\n    if x > 0 and y.startswith('test'):\n        return True\n    return False\n" * 5
        iterations = 100
        start = time.monotonic()
        for _ in range(iterations):
            count_tokens(typical)
        elapsed_ms = (time.monotonic() - start) / iterations * 1000
        self.assertLess(elapsed_ms, 50, f"estimation too slow: {elapsed_ms:.2f}ms")

    def test_repeated_calls_fast(self):
        text = "The quick brown fox jumps over the lazy dog. " * 100
        start = time.monotonic()
        for _ in range(1000):
            count_tokens(text)
        elapsed_ms = (time.monotonic() - start) / 1000 * 1000
        self.assertLess(elapsed_ms, 15.0, f"estimation too slow: {elapsed_ms:.3f}ms")


class TestSpecialCharacters(unittest.TestCase):
    """Various special characters and Unicode."""

    def test_newline_separated(self):
        self.assertIn(count_tokens("a\nb\nc\nd\ne"), range(3, 9))

    def test_tab_separated(self):
        self.assertIn(count_tokens("col1\tcol2\tcol3"), range(3, 8))

    def test_smart_quotes_similar(self):
        t1 = count_tokens("'Hello'")
        t2 = count_tokens("ʻHelloʻ")
        self.assertLessEqual(abs(t1 - t2), 1)


class TestKnownPatterns(unittest.TestCase):
    """Patterns with well-known cl100k_base token counts."""

    def test_hello_world_exclamation(self):
        self.assertIn(count_tokens("Hello world!"), range(2, 5))

    def test_single_word_the(self):
        self.assertEqual(count_tokens("the"), 1)

    def test_number_in_text(self):
        self.assertIn(count_tokens("I have 42 apples"), range(3, 7))


class TestCodeIdentifiers(unittest.TestCase):
    """Code identifiers with various naming conventions."""

    def test_snake_case(self):
        self.assertIn(count_tokens("my_very_long_variable_name"), range(3, 9))

    def test_camel_case(self):
        self.assertIn(count_tokens("myVariableName"), range(1, 5))

    def test_pascal_case(self):
        self.assertIn(count_tokens("MyClassName"), range(1, 5))


class TestContractions(unittest.TestCase):
    """Contractions and apostrophes."""

    def test_contractions(self):
        for c in ["don't", "can't", "I'm", "you're", "they'll", "won't"]:
            self.assertIn(count_tokens(c), range(1, 4), f"contraction '{c}'")


class TestMultiline(unittest.TestCase):
    """Multi-line strings."""

    def test_multiline_string(self):
        text = (
            "Here is a multi-line string:\n"
            "Line one\nLine two\nLine three\n\n"
            "With an empty line above."
        )
        self.assertIn(count_tokens(text), range(10, 26))


class TestRepetitivePatterns(unittest.TestCase):
    """Repetitive text patterns (like log output)."""

    def test_repeated_lines_scale(self):
        line = "INFO:root:Processing item 42\n"
        repeated = line * 50
        t = count_tokens(repeated)
        single_line_t = count_tokens(line.strip())
        expected = single_line_t * 50
        self.assertGreaterEqual(t, 0.5 * expected)
        self.assertLessEqual(t, 1.5 * expected)


if __name__ == "__main__":
    unittest.main()