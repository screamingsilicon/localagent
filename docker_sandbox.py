"""Docker sandbox module for localagent.

Provides an isolated Docker container environment where the agent can
execute shell commands and read/write files without affecting the host
system directly. The agent process runs on the host but all tool
executions are routed into the sandbox container.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import time
from typing import Tuple, Optional


IMAGE_NAME = "localagent-image"
DOCKERFILE = """FROM python:3.12-alpine
RUN apk add --no-cache git tmux
WORKDIR /workspace
"""

SHELL_OUTPUT_BG = "\033[48;5;235;90m"
CLEAR_LINE = "\033[K"
RESET = "\033[0m"


_SANDBOX_CONTAINER: Optional[str] = None


def get_container_name() -> Optional[str]:
    """Return the current sandbox container name, or None if not running."""
    return _SANDBOX_CONTAINER


def ensure_docker_image() -> None:
    """Build the localagent Docker image if it doesn't already exist."""
    if subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME], capture_output=True
    ).returncode == 0:
        return

    print(f"[*] Docker image '{IMAGE_NAME}' not found. Building it automatically...")
    try:
        subprocess.run(
            ["docker", "build", "-t", IMAGE_NAME, "-"],
            input=DOCKERFILE,
            text=True,
            check=True,
            capture_output=True,
        )
        print("[*] Image built successfully!\n")
    except subprocess.CalledProcessError:
        print("[!] Error: Failed to build the Docker image. Ensure Docker is running.")
        sys.exit(1)


def setup_sandbox(cpus: Optional[float] = None, memory: Optional[str] = None) -> str:
    """Create a persistent sandbox container with no network access.

    The agent runs on the host but all tool commands are executed inside
    the container via ``docker exec``.

    Args:
        cpus: CPU core limit (e.g. 2.0, 0.5). Passed as ``--cpus`` to docker.
        memory: Memory limit string (e.g. '4g', '512m'). Passed as ``--memory``.

    Returns:
        The name of the created container.
    """
    global _SANDBOX_CONTAINER

    ensure_docker_image()

    _SANDBOX_CONTAINER = f"agent-sandbox-{os.getpid()}-{int(time.time())}"

    cmd: list[str] = [
        "docker", "run", "-d", "--name", _SANDBOX_CONTAINER,
        "--network", "none",
        "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp:exec",
        "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
        "-v", f"{os.getcwd()}:/workspace:rw", "-w", "/workspace",
    ]
    if cpus is not None:
        cmd.extend(["--cpus", str(cpus)])
    if memory is not None:
        cmd.extend(["--memory", memory])
    cmd.extend([IMAGE_NAME, "tail", "-f", "/dev/null"])

    subprocess.run(cmd, check=True, capture_output=True)
    atexit.register(_teardown_sandbox)

    return _SANDBOX_CONTAINER


def _teardown_sandbox() -> None:
    if _SANDBOX_CONTAINER:
        subprocess.run(
            ["docker", "rm", "-f", _SANDBOX_CONTAINER], capture_output=True
        )


def docker_exec(cmd: str, cwd: Optional[str] = None) -> Tuple[list[str], int]:
    """Execute a command inside the sandbox container, streaming output.

    Args:
        cmd: Shell command to run.
        cwd: Working directory (unused — always /workspace). Kept for API
             compatibility with the local-path version.

    Returns:
        Tuple of (list-of-output-lines, return-code).
    """
    docker_cmd = ["docker", "exec", "-i", _SANDBOX_CONTAINER, "sh", "-c", cmd]
    p = subprocess.Popen(
        docker_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    try:
        for line in p.stdout:
            lines.append(line.rstrip("\n"))
            w = shutil.get_terminal_size((80, 20)).columns
            print(
                f"{SHELL_OUTPUT_BG}{line.rstrip().ljust(w)}{CLEAR_LINE}{RESET}",
                end="\n",
            )
        p.wait()
    except KeyboardInterrupt:
        p.terminate()
        try:
            p.wait(timeout=2)
        except Exception:
            p.kill()
        lines.append("[Interrupted]")
    return lines, p.returncode


def docker_exec_file_write(path: str, content: str) -> int:
    """Write file content inside the sandbox via stdin pipe.

    Args:
        path: Path inside the container (e.g. '/workspace/foo.py').
        content: File contents to write.

    Returns:
        Return code from docker exec (0 on success).
    """
    p = subprocess.run(
        ["docker", "exec", "-i", _SANDBOX_CONTAINER, "sh", "-c", f"cat > '{path}'"],
        input=content,
        text=True,
        capture_output=True,
    )
    return p.returncode


def docker_exec_read_file(path: str) -> Tuple[Optional[str], Optional[str]]:
    """Read file content from inside the sandbox container.

    Args:
        path: Path inside the container (e.g. '/workspace/foo.py').

    Returns:
        Tuple of (content, error). On success *error* is ``None``; on failure
        *content* is ``None`` and *error* holds the stderr message.
    """
    p = subprocess.run(
        ["docker", "exec", _SANDBOX_CONTAINER, "cat", path],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return None, p.stderr.strip()
    return p.stdout, None