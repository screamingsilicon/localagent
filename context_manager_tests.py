"""Tests for context_manager module — file path extraction and context compaction."""

from __future__ import annotations

import unittest


class TestExtractFilePaths(unittest.TestCase):
    """Extract file paths from shell output."""

    def test_reads(self):
        from context_manager import _extract_file_paths

        content = (
            "cat config.py\n"
            "head app.js\n"
            "tail README.md\n"
            "Error reading utils.rs: not found\n"
        )
        reads, mods = _extract_file_paths(content)
        self.assertIn("config.py", reads)
        self.assertIn("app.js", reads)

    def test_modifications(self):
        from context_manager import _extract_file_paths

        content = (
            "Successfully edited app.py\n"
            "Wrote content to new_module.js\n"
            "Successfully edited config.yaml\n"
        )
        reads, mods = _extract_file_paths(content)
        self.assertIn("app.py", mods)
        self.assertIn("new_module.js", mods)
        self.assertIn("config.yaml", mods)

    def test_deduplicates(self):
        from context_manager import _extract_file_paths

        content = (
            "Successfully edited app.py\n"
            "Successfully edited app.py\n"
            "cat app.py\n"
        )
        reads, mods = _extract_file_paths(content)
        self.assertLessEqual(reads.count("app.py"), 1)
        self.assertLessEqual(mods.count("app.py"), 1)


class TestCompressContext(unittest.TestCase):
    """Token estimation and context compaction."""

    def test_uses_provider_usage(self):
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
        self.assertIsNotNone(result_msgs)

    def test_fallback_char_based(self):
        from context_manager import compress_context

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        result_msgs, summary = compress_context(
            messages, "", config=None, llm_request_fn=lambda x, **kw: None
        )
        self.assertIsNotNone(result_msgs)

    def test_incremental_summary_prompt_structure(self):
        from context_manager import compress_context

        mock_responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "## Goal\nFirst task.\n## Progress\n### Done\n- [x] step 1"
                        }
                    }
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
        self.assertIsInstance(result_msgs, list)


class TestSystemPrompt(unittest.TestCase):
    """Verify system_prompt.md has required guidance."""

    def setUp(self):
        from pathlib import Path

        self.prompt = Path("/workspace/system_prompt.md").read_text()

    def test_has_multi_edit_guidance(self):
        self.assertIn("multiple", self.prompt.lower())
        self.assertTrue(
            "batch" in self.prompt.lower() or "single" in self.prompt.lower(),
            "Should suggest batching",
        )
        self.assertIn("done", self.prompt.lower())

    def test_has_find_block_guidance(self):
        self.assertIn("unique", self.prompt.lower())
        self.assertTrue(
            "small" in self.prompt.lower() or "minimal" in self.prompt.lower(),
            "Should suggest minimal find blocks",
        )


if __name__ == "__main__":
    unittest.main()