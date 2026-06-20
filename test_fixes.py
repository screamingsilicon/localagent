"""Tests for TODO.md fixes applied to localagent.py and session_manager.py."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

LA_PATH = Path("/workspace/localagent.py")


class TestSessionManagerLogEvent(unittest.TestCase):
    """P3#10: Verify log_event() public method on SessionManager."""

    def test_log_event_exists_and_works(self):
        from session_manager import SessionManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.log_event("test_event")
            with open(mgr.session_file) as f:
                lines = f.readlines()
            last = json.loads(lines[-1])
            self.assertEqual(last["type"], "event")
            self.assertEqual(last["event"], "test_event")

    def test_log_event_with_extra(self):
        from session_manager import SessionManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = SessionManager(tmp)
            mgr.log_event("custom", {"detail": "foo"})
            with open(mgr.session_file) as f:
                lines = f.readlines()
            last = json.loads(lines[-1])
            self.assertEqual(last["detail"], "foo")


class TestTokenEstimation(unittest.TestCase):
    """P1#3: Context window overflow protection helpers using count_tokens_messages."""

    def _make_agent(self):
        from localagent import LocalAgent
        with patch.object(LocalAgent, '__init__', lambda self, **kw: None):
            agent = LocalAgent()
            agent.messages = []
            agent._compaction_summary = ""
            return agent

    def test_estimate_tokens_empty(self):
        agent = self._make_agent()
        self.assertEqual(agent._estimate_tokens(), 0)

    def test_estimate_tokens_basic(self):
        """_estimate_tokens delegates to count_tokens_messages."""
        from token_counter import count_tokens_messages
        agent = self._make_agent()
        agent.messages = [{"role": "user", "content": "hello world"}]
        expected = count_tokens_messages(agent.messages)
        self.assertEqual(agent._estimate_tokens(), expected)
        self.assertGreater(expected, 0)

    def test_estimate_tokens_multiple_messages(self):
        """Token count increases with more messages."""
        from token_counter import count_tokens_messages
        agent = self._make_agent()
        msgs = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I am doing well, thank you for asking!"},
        ]
        agent.messages = msgs
        expected = count_tokens_messages(msgs)
        self.assertEqual(agent._estimate_tokens(), expected)
        # Verify it's more than a single message would be
        single = count_tokens_messages([msgs[0]])
        self.assertGreater(expected, single)


class TestEnsureContextFits(unittest.TestCase):
    """P1#3: _ensure_context_fits force-compacts near overflow."""

    def test_ensure_context_triggers_compaction_near_limit(self):
        from localagent import LocalAgent
        # Use varied content that doesn't compress as well (unique words)
        varied = " ".join(f"word{i}" for i in range(500))  # ~500 unique tokens
        with patch('localagent._Config') as mock_config:
            mock_config.context_window.return_value = 1000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": varied}]
            agent.compress_context = MagicMock()
            agent._ensure_context_fits()
            agent.compress_context.assert_called_once()

    def test_ensure_context_skips_when_under_limit(self):
        from localagent import LocalAgent
        with patch('localagent._Config') as mock_config:
            mock_config.context_window.return_value = 100000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 400}]
            agent.compress_context = MagicMock()
            agent._ensure_context_fits()
            agent.compress_context.assert_not_called()


class TestMaybeCompressContext(unittest.TestCase):
    """P3#9: _maybe_compress_context only compacts above threshold."""

    def test_maybe_compress_triggers_above_threshold(self):
        from localagent import LocalAgent
        with patch('localagent._Config') as mock_config:
            mock_config.context_window.return_value = 1000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 4000}]
            agent.compress_context = MagicMock()
            agent._maybe_compress_context()
            agent.compress_context.assert_called_once()

    def test_maybe_compress_skips_below_threshold(self):
        from localagent import LocalAgent
        with patch('localagent._Config') as mock_config:
            mock_config.context_window.return_value = 10000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 200}]
            agent.compress_context = MagicMock()
            agent._maybe_compress_context()
            agent.compress_context.assert_not_called()


class TestNoOpRegexRemoved(unittest.TestCase):
    """P0#1: Verify no-op re.sub is gone."""

    def test_no_re_sub_in_file(self):
        self.assertNotIn("re.sub", LA_PATH.read_text(), "no-op re.sub should be removed")
        lines = LA_PATH.read_text().splitlines()
        import_lines = [l for l in lines if l.startswith("import re") or l.startswith("from re")]
        self.assertEqual(import_lines, [], f"re import should be removed: {import_lines}")


class TestDeadCodeRemoved(unittest.TestCase):
    """P1#4: Dead code 'and True' removed."""

    def test_no_and_true(self):
        self.assertNotIn("and True", LA_PATH.read_text(), "dead code 'and True' should be removed")


class TestErrorLogging(unittest.TestCase):
    """P0#2: _run_in_container logs warnings on failure (uses lazy docker_sandbox loader)."""

    def test_logs_warning_on_no_container(self):
        import localagent
        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = None
        with patch.object(localagent, '_get_docker_sandbox', return_value=mock_ds):
            with patch.object(localagent._log, 'warning') as mock_warn:
                localagent._run_in_container("echo hi")
                mock_warn.assert_called_once()
                self.assertIn("No container name", str(mock_warn.call_args))

    def test_logs_warning_on_timeout(self):
        import localagent
        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = "test-container"
        with patch.object(localagent, '_get_docker_sandbox', return_value=mock_ds):
            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5)):
                with patch.object(localagent._log, 'warning') as mock_warn:
                    localagent._run_in_container("slow cmd")
                    mock_warn.assert_called_once()
                    self.assertIn("timed out", str(mock_warn.call_args))

    def test_logs_warning_on_generic_exception(self):
        import localagent
        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = "test-container"
        with patch.object(localagent, '_get_docker_sandbox', return_value=mock_ds):
            with patch('subprocess.run', side_effect=RuntimeError("boom")):
                with patch.object(localagent._log, 'warning') as mock_warn:
                    localagent._run_in_container("bad cmd")
                    mock_warn.assert_called_once()
                    self.assertIn("boom", str(mock_warn.call_args))


class TestBatchContainerProbe(unittest.TestCase):
    """P2#5: Verify batch probing uses null-byte delimiter (robust against command output)."""

    def test_probe_uses_delimiter(self):
        text = LA_PATH.read_text()
        self.assertIn("\\x00", text, "batch probe should use \\x00 (null byte) delimiter")
        self.assertIn("set -euo pipefail", text, "should set strict mode")

    def test_batch_probe_parses_output(self):
        import localagent
        # Null-byte separated output format
        fake_output = "\x00".join([
            "6.8.0-test",
            "Python 3.12.13",
            "/bin/bash",
            "agent",
            "4",
            "MemTotal:       4194304 kB",
            "/usr/bin/git\n/usr/bin/node\n/usr/bin/jq",
        ]) + "\x00"

        with patch.object(localagent, '_run_in_container', return_value=fake_output):
            info = localagent._container_system_info()

        self.assertEqual(info["release"], "6.8.0-test")
        self.assertEqual(info["python"], "Python 3.12.13")
        self.assertEqual(info["shell"], "/bin/bash")
        self.assertEqual(info["user"], "agent")
        self.assertEqual(info["cpu_cores"], 4)
        self.assertEqual(info["memory_total_gb"], 4.0)
        self.assertIn("git", info["available_tools"])


class TestTurnTimeout(unittest.TestCase):
    """P2#7: Turn timeout guard exists."""

    def test_turn_timeout_constant(self):
        text = LA_PATH.read_text()
        self.assertIn("_TURN_TIMEOUT", text, "timeout constant should be defined")
        self.assertIn("= 600", text, "timeout should be 600 seconds")
        self.assertIn("time.monotonic()", text, "should use monotonic clock")


class TestSafeDockerSandboxImport(unittest.TestCase):
    """P2#8: ImportError is caught via lazy loader in _get_docker_sandbox."""

    def test_lazy_loader_exists(self):
        import localagent
        self.assertTrue(hasattr(localagent, '_get_docker_sandbox'))
        self.assertTrue(callable(localagent._get_docker_sandbox))

    def test_lazy_loader_returns_none_on_import_error(self):
        import localagent
        # Reset the cached module to None for testing
        localagent._docker_sandbox_module = None
        with patch('builtins.__import__', side_effect=ImportError("no docker")):
            result = localagent._get_docker_sandbox()
            self.assertIsNone(result)


class TestPrivateMemberAccessRemoved(unittest.TestCase):
    """P3#10: No more _write_log access from localagent."""

    def test_no_write_log_access(self):
        self.assertNotIn("_session_mgr._write_log", LA_PATH.read_text(),
                         "_session_mgr._write_log should not be called directly")


if __name__ == "__main__":
    unittest.main(verbosity=2)