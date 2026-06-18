
"""Tests for docker_sandbox.py — uses mocks so no real Docker needed."""

from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock, call


class TestDockerSandbox(unittest.TestCase):
    """Unit tests with mocked subprocess calls."""

    def setUp(self):
        
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = None
        self.ds = ds

    def tearDown(self):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = None

    @patch("docker_sandbox.subprocess.run")
    def test_ensure_docker_image_skips_if_exists(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.ds.ensure_docker_image()
        
        calls = [c for c in mock_run.call_args_list if "build" in str(c)]
        self.assertEqual(len(calls), 0)

    @patch("docker_sandbox.subprocess.run")
    def test_ensure_docker_image_builds_if_missing(self, mock_run):
        
        
        mock_run.side_effect = [
            MagicMock(returncode=1),  
            MagicMock(returncode=0),  
        ]
        self.ds.ensure_docker_image()
        
        self.assertEqual(mock_run.call_count, 2)

    @patch("docker_sandbox.subprocess.run")
    @patch("docker_sandbox.atexit.register")
    def test_setup_sandbox_creates_container(self, mock_atexit, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        name = self.ds.setup_sandbox()
        self.assertTrue(name.startswith("agent-sandbox-"))
        
        call_args = mock_run.call_args[0][0]
        self.assertIn("docker", call_args)
        self.assertIn("run", call_args)

    @patch("docker_sandbox.subprocess.run")
    @patch("docker_sandbox.atexit.register")
    def test_setup_sandbox_with_limits(self, mock_atexit, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        self.ds.setup_sandbox(cpus=2.0, memory="4g")
        call_args = mock_run.call_args[0][0]
        self.assertIn("--cpus", call_args)
        self.assertIn("2.0", call_args)
        self.assertIn("--memory", call_args)
        self.assertIn("4g", call_args)

    def test_get_container_name_none_by_default(self):
        self.assertIsNone(self.ds.get_container_name())

    @patch("docker_sandbox.subprocess.Popen")
    def test_docker_exec_streams_output(self, mock_popen):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n", "line2\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        mock_popen.return_value = mock_proc

        lines, rc = self.ds.docker_exec("echo hi")
        self.assertEqual(lines, ["line1", "line2"])
        self.assertEqual(rc, 0)

    @patch("docker_sandbox.subprocess.Popen")
    def test_docker_exec_keyboard_interrupt(self, mock_popen):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["partial\n"])
        
        def raise_ki(iterator):
            yield next(iter(iterator))
            raise KeyboardInterrupt
        mock_proc.stdout = raise_ki(iter(["line1\n"]))
        mock_proc.returncode = 130
        mock_proc.wait.return_value = None
        mock_popen.return_value = mock_proc

        lines, rc = self.ds.docker_exec("sleep 100")
        self.assertIn("[Interrupted]", lines)

    @patch("docker_sandbox.subprocess.run")
    def test_docker_exec_file_write(self, mock_run):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"
        mock_run.return_value = MagicMock(returncode=0)

        rc = self.ds.docker_exec_file_write("/workspace/test.txt", "hello")
        self.assertEqual(rc, 0)
        
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        self.assertEqual(call_kwargs["input"], "hello")

    @patch("docker_sandbox.subprocess.run")
    def test_docker_exec_read_file_success(self, mock_run):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"
        mock_run.return_value = MagicMock(returncode=0, stdout="file content", stderr="")

        content, error = self.ds.docker_exec_read_file("/workspace/test.txt")
        self.assertEqual(content, "file content")
        self.assertIsNone(error)

    @patch("docker_sandbox.subprocess.run")
    def test_docker_exec_read_file_failure(self, mock_run):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such file")

        content, error = self.ds.docker_exec_read_file("/no/file")
        self.assertIsNone(content)
        self.assertEqual(error, "No such file")

    def test_teardown_sandbox(self):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = "test-container"

        with patch("docker_sandbox.subprocess.run") as mock_run:
            ds._teardown_sandbox()
            call_args = mock_run.call_args[0][0]
            self.assertIn("rm", call_args)
            self.assertIn("-f", call_args)
            self.assertIn("test-container", call_args)

    def test_teardown_sandbox_no_container(self):
        import docker_sandbox as ds
        ds._SANDBOX_CONTAINER = None
        
        ds._teardown_sandbox()


class TestConstants(unittest.TestCase):
    """Test that module constants are sensible."""

    def test_image_name(self):
        self.assertEqual(self.ds.IMAGE_NAME, "localagent-image")

    def test_dockerfile_has_python(self):
        self.assertIn("python", self.ds.DOCKERFILE)

    @property
    def ds(self):
        import docker_sandbox
        return docker_sandbox


if __name__ == "__main__":
    unittest.main()