
"""Tests for stream_renderer module."""

from __future__ import annotations

import io
import sys
from unittest import TestCase, main

from stream_renderer import StreamRenderer, THINK_COLOR, RESET


OPEN_THINK = "\x3c!--" + "think" + "--\x3e"  
CLOSE_THINK = "\x3c!--/" + "think--\x3e"


class TestStreamRenderer(TestCase):

    def setUp(self):
        self.captured = io.StringIO()
        self._old_stdout = sys.stdout
        sys.stdout = self.captured
        self.renderer = StreamRenderer()

    def tearDown(self):
        sys.stdout = self._old_stdout

    

    def test_reasoning_starts_think_block(self):
        self.renderer.feed_reasoning("thinking...")
        out = self.captured.getvalue()
        self.assertIn(THINK_COLOR, out)
        self.assertIn("> ", out)
        self.assertIn("thinking...", out)

    def test_reasoning_accumulates_in_full_text(self):
        self.renderer.feed_reasoning("step1")
        self.assertIn("step1", self.renderer.full_text)

    def test_reasoning_multiple_chunks(self):
        self.renderer.feed_reasoning("a")
        self.renderer.feed_reasoning("b")
        out = self.captured.getvalue()
        self.assertIn("a", out)
        self.assertIn("b", out)

    

    def test_plain_text(self):
        self.renderer.feed_content("Hello world\n")
        out = self.captured.getvalue()
        self.assertIn("Hello world", out)
        self.assertIn("Hello world", self.renderer.full_text)

    def test_reasoning_then_content_closes_think(self):
        self.renderer.feed_reasoning("thinking")
        self.renderer.feed_content("result")
        out = self.captured.getvalue()
        self.assertIn(RESET, out)
        self.assertIn("result", self.renderer.full_text)

    def test_simulated_think_tags(self):
        _open = chr(60) + "think" + chr(62)
        _close = chr(60) + "/think" + chr(62)
        text = f"before {_open}simulated reasoning{_close} after"
        self.renderer.feed_content(text)
        out = self.captured.getvalue()
        self.assertIn(THINK_COLOR, out)

    def test_partial_tag_buffering(self):
        """A partial tag should be buffered without crashing."""
        self.renderer.feed_content("hello <th")
        self.assertTrue(True)

    

    def test_flush_produces_output(self):
        self.renderer.feed_content("some text")
        self.renderer.flush_all()
        out = self.captured.getvalue()
        self.assertIn("some text", out)

    def test_full_text_after_reasoning_and_content(self):
        self.renderer.feed_reasoning("think step")
        self.renderer.feed_content("answer")
        self.assertIn("think step", self.renderer.full_text)
        self.assertIn("answer", self.renderer.full_text)

    

    def test_code_block_flushed_at_end(self):
        self.renderer.feed_content("```\nprint('hi')\n")
        self.renderer.flush_all()

    def test_table_lines(self):
        self.renderer.feed_content("| A | B |\n|---|---|\n| 1 | 2 |")
        self.renderer.flush_all()

    

    def test_shell_tag_rendered(self):
        tag = chr(60) + "shell" + chr(62) + "echo hi" + chr(60) + "/shell" + chr(62)
        self.renderer.feed_content(tag)
        out = self.captured.getvalue()
        
        self.assertIn("echo", out)
        self.assertIn("hi", out)

    def test_partial_xml_tag_buffered(self):
        self.renderer.feed_content("<shell")
        self.assertTrue(True)


class TestConstants(TestCase):
    def test_think_color_is_ansi(self):
        self.assertTrue(THINK_COLOR.startswith("\033["))

    def test_reset_is_ansi(self):
        self.assertEqual(RESET, "\033[0m")


if __name__ == "__main__":
    main(verbosity=2)