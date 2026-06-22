"""Tests for localagent module — context management, error handling, Docker integration."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

LA_PATH = Path("/workspace/localagent.py")


class TestTokenEstimation(unittest.TestCase):
    """Context window overflow protection helpers using count_tokens_messages."""

    def _make_agent(self):
        from localagent import LocalAgent

        with patch.object(LocalAgent, "__init__", lambda self, **kw: None):
            agent = LocalAgent()
            agent.messages = []
            agent._compaction_summary = ""
            return agent

    def test_estimate_tokens_empty(self):
        agent = self._make_agent()
        self.assertEqual(agent._estimate_tokens(), 0)

    def test_estimate_tokens_basic(self):
        from token_counter import count_tokens_messages

        agent = self._make_agent()
        agent.messages = [{"role": "user", "content": "hello world"}]
        expected = count_tokens_messages(agent.messages)
        self.assertEqual(agent._estimate_tokens(), expected)
        self.assertGreater(expected, 0)

    def test_estimate_tokens_multiple_messages(self):
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
        single = count_tokens_messages([msgs[0]])
        self.assertGreater(expected, single)


class TestEnsureContextFits(unittest.TestCase):
    """_ensure_context_fits force-compacts near overflow."""

    def test_triggers_compaction_near_limit(self):
        from localagent import LocalAgent

        varied = " ".join(f"word{i}" for i in range(500))
        with patch("localagent._Config") as mock_config:
            mock_config.context_window.return_value = 1000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": varied}]
            agent.compress_context = MagicMock()
            agent._ensure_context_fits()
            agent.compress_context.assert_called_once()

    def test_skips_when_under_limit(self):
        from localagent import LocalAgent

        with patch("localagent._Config") as mock_config:
            mock_config.context_window.return_value = 100000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 400}]
            agent.compress_context = MagicMock()
            agent._ensure_context_fits()
            agent.compress_context.assert_not_called()


class TestMaybeCompressContext(unittest.TestCase):
    """_maybe_compress_context only compacts above threshold."""

    def test_triggers_above_threshold(self):
        from localagent import LocalAgent

        with patch("localagent._Config") as mock_config:
            mock_config.context_window.return_value = 1000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 4000}]
            agent.compress_context = MagicMock()
            agent._maybe_compress_context()
            agent.compress_context.assert_called_once()

    def test_skips_below_threshold(self):
        from localagent import LocalAgent

        with patch("localagent._Config") as mock_config:
            mock_config.context_window.return_value = 10000
            agent = LocalAgent.__new__(LocalAgent)
            agent.messages = [{"role": "user", "content": "X" * 200}]
            agent.compress_context = MagicMock()
            agent._maybe_compress_context()
            agent.compress_context.assert_not_called()


class TestErrorLogging(unittest.TestCase):
    """_run_in_container logs warnings on failure."""

    def test_logs_warning_on_no_container(self):
        import localagent

        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = None
        with patch.object(localagent, "_get_docker_sandbox", return_value=mock_ds):
            with patch.object(localagent._log, "warning") as mock_warn:
                localagent._run_in_container("echo hi")
                mock_warn.assert_called_once()
                self.assertIn("No container name", str(mock_warn.call_args))

    def test_logs_warning_on_timeout(self):
        import localagent

        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = "test-container"
        with patch.object(localagent, "_get_docker_sandbox", return_value=mock_ds):
            with patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5)
            ):
                with patch.object(localagent._log, "warning") as mock_warn:
                    localagent._run_in_container("slow cmd")
                    mock_warn.assert_called_once()
                    self.assertIn("timed out", str(mock_warn.call_args))

    def test_logs_warning_on_generic_exception(self):
        import localagent

        mock_ds = MagicMock()
        mock_ds.get_container_name.return_value = "test-container"
        with patch.object(localagent, "_get_docker_sandbox", return_value=mock_ds):
            with patch("subprocess.run", side_effect=RuntimeError("boom")):
                with patch.object(localagent._log, "warning") as mock_warn:
                    localagent._run_in_container("bad cmd")
                    mock_warn.assert_called_once()
                    self.assertIn("boom", str(mock_warn.call_args))


class TestBatchContainerProbe(unittest.TestCase):
    """Batch probing uses null-byte delimiter."""

    def test_probe_uses_delimiter(self):
        text = LA_PATH.read_text()
        self.assertIn("\\x00", text)
        self.assertIn("set -euo pipefail", text)

    def test_batch_probe_parses_output(self):
        import localagent

        fake_output = "\x00".join(
            [
                "6.8.0-test",
                "Python 3.12.13",
                "/bin/bash",
                "agent",
                "4",
                "MemTotal:       4194304 kB",
                "/usr/bin/git\n/usr/bin/node\n/usr/bin/jq",
            ]
        ) + "\x00"

        with patch.object(localagent, "_run_in_container", return_value=fake_output):
            info = localagent._container_system_info()

        self.assertEqual(info["release"], "6.8.0-test")
        self.assertEqual(info["python"], "Python 3.12.13")
        self.assertEqual(info["shell"], "/bin/bash")
        self.assertEqual(info["user"], "agent")
        self.assertEqual(info["cpu_cores"], 4)
        self.assertEqual(info["memory_total_gb"], 4.0)
        self.assertIn("git", info["available_tools"])


class TestTurnTimeout(unittest.TestCase):
    """Turn timeout guard exists."""

    def test_turn_timeout_constant(self):
        text = LA_PATH.read_text()
        self.assertIn("_TURN_TIMEOUT", text)
        self.assertIn("= 600", text)
        self.assertIn("time.monotonic()", text)


class TestSafeDockerSandboxImport(unittest.TestCase):
    """ImportError is caught via lazy loader in _get_docker_sandbox."""

    def test_lazy_loader_exists(self):
        import localagent

        self.assertTrue(hasattr(localagent, "_get_docker_sandbox"))
        self.assertTrue(callable(localagent._get_docker_sandbox))

    def test_lazy_loader_returns_none_on_import_error(self):
        import localagent

        localagent._docker_sandbox_module = None
        with patch("builtins.__import__", side_effect=ImportError("no docker")):
            result = localagent._get_docker_sandbox()
            self.assertIsNone(result)


class TestCodeQuality(unittest.TestCase):
    """Verify code quality improvements from TODO.md fixes."""

    def test_no_re_sub_in_file(self):
        text = LA_PATH.read_text()
        self.assertNotIn("re.sub", text)
        lines = text.splitlines()
        import_lines = [l for l in lines if l.startswith("import re") or l.startswith("from re")]
        self.assertEqual(import_lines, [])

    def test_no_and_true_dead_code(self):
        text = LA_PATH.read_text()
        self.assertNotIn("and True", text)

    def test_no_write_log_access(self):
        text = LA_PATH.read_text()
        self.assertNotIn("_session_mgr._write_log", text)


if __name__ == "__main__":
    unittest.main()