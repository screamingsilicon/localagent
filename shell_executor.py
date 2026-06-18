from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path


def run_command(cmd: str) -> str | None:
    """Run a shell command and return stripped output, or None on failure."""
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except Exception:
        return None


def is_safe_read_command(cmd: str) -> bool:
    """Check if a command is a safe read-only operation."""
    safe_bins = {"cat", "sed", "head", "tail", "wc", "grep", "find", "ls", "pwd", "echo", "date", "file", "which"}
    dang_pats = {"| rm", "xargs rm", "| sh", "| bash", ">", "; rm", "; mv", "&& rm", "`", "$("}

    c = cmd.strip()
    words = c.split()
    if not words or words[0] not in safe_bins or any(p in c for p in dang_pats):
        return False
    if words[0] == "sed" and "-i" in c:
        return False
    if words[0] == "find" and any(f in c for f in ("-exec", "-delete")):
        return False
    return True


def stream_command_output(exec_cmd: str, color_code: str = "90m", cwd: str = None, sandbox: bool = False, timeout: int = 60) -> tuple[list[str], int]:
    """Stream command output to terminal with optional coloring and timeout."""
    if sandbox:
        import docker_sandbox
        return docker_sandbox.docker_exec(exec_cmd)

    from display import SHELL_OUTPUT_BG, CLEAR_LINE, RESET

    shell_bin = shutil.which("bash") or "/bin/sh"
    p = subprocess.Popen(exec_cmd, shell=True, executable=shell_bin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=cwd or os.getcwd())
    lines = []
    # Watchdog thread to kill the process if it exceeds timeout
    killed_by_watchdog = threading.Event()

    def _watchdog():
        time.sleep(timeout)
        if p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=3)
            except Exception:
                p.kill()
            killed_by_watchdog.set()

    wd = threading.Thread(target=_watchdog, daemon=True)
    wd.start()

    interrupted = False
    try:
        for l in p.stdout:
            if not color_code:
                print(l, end="")
            elif color_code == "90m":
                w = shutil.get_terminal_size((80, 20)).columns
                print(f"{SHELL_OUTPUT_BG}{l.rstrip().ljust(w)}{CLEAR_LINE}{RESET}", end="\n")
            else:
                print(f"\033[{color_code}{l.rstrip()}\033[0m", end="\n")
            lines.append(l.rstrip('\n'))

        p.wait()
    except KeyboardInterrupt:
        interrupted = True
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()
        lines.append("[Interrupted]")

    # Determine if the process was killed by the timeout watchdog
    timed_out = killed_by_watchdog.is_set() or (p.returncode is not None and p.returncode < 0 and not interrupted)

    if timed_out and "[Timed out]" not in "\n".join(lines):
        lines.append("[Timed out after {}s]".format(timeout))

    return lines, p.returncode


class _SudoCache:
    """Per-instance sudo password cache."""
    def __init__(self):
        self._cache: dict[str, str] = {}

    def get_password(self, remote: str) -> str | None:
        import base64
        import getpass
        from display import BOLD, RESET

        encoded = self._cache.get(remote)
        if encoded:
            return base64.b64decode(encoded).decode()
        print(f"\033[33m[sudo] password for {remote}:\033[0m", end=" ", flush=True)
        try:
            pw = getpass.getpass()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not pw:
            print("\033[31m[No password provided. sudo commands will fail.]\033[0m")
            return None
        self._cache[remote] = base64.b64encode(pw.encode()).decode()
        return pw

    def wrap_sudo_cmd(self, cmd: str, remote: str) -> tuple[str, str]:
        """Wrap a command that uses sudo with password piping.

        Uses ``sudo -S bash -c`` so the entire command runs inside an
        already-authenticated root shell  &mdash; any *chained* sudo
        calls (e.g. ``sudo apt update && sudo apt install foo``) inherit
        the cached credentials instead of hanging for a second password.

        The inner command body is base64-encoded to completely sidestep
        quoting / escaping issues with single quotes, double quotes,
        backticks, dollar-signs, pipes, etc.
        """
        if not re.search(r'(^|\s|;|&&|\|\|)sudo\b', cmd):
            return cmd, cmd

        pw = self.get_password(remote)
        if pw is None:
            return cmd, cmd

        # Base64-encode the command body so it survives ALL quoting contexts
        encoded_cmd = base64.b64encode(cmd.encode()).decode()

        # Escape password for single-quote context (only char we need to worry about)
        escaped_pw = pw.replace("'", "'\\''")

        # sudo -S authenticates once; bash inherits cached credentials so
        # any subsequent ``sudo`` inside the command body works without
        # asking again.
        wrapped = (
            f"echo '{escaped_pw}' | sudo -S bash -c "
            f"'echo {encoded_cmd} | base64 -d | bash'"
        )
        return wrapped, cmd


def execute_shell(act: dict, auto_mode: bool, cwd: str, sandbox: bool, sudo_cache: _SudoCache, log_tool_call=None) -> str:
    """Execute a shell action and return the result string."""
    import tempfile

    from highlighters import highlight_bash
    from display import BOLD, RESET

    cmd = act["command"]
    remote = act.get("remote")
    timeout = act.get("timeout", 60)
    safe = is_safe_read_command(cmd) and not remote
    highlighted_cmd = highlight_bash(cmd)
    prefix_color = "90m" if safe else "36m"
    remote_prefix = f"[{remote}] " if remote else ""
    timeout_suffix = f"\033[90m (⏱ {timeout}s)\033[0m" if timeout != 60 else ""
    print(f"\033[{prefix_color}$ {remote_prefix}\033[0m{highlighted_cmd}{timeout_suffix}")

    if not safe and not auto_mode:
        print(f"{BOLD}(y/n): {RESET}", end="", flush=True)
        try:
            if input().strip().lower() != 'y':
                if log_tool_call: log_tool_call("shell", False, {"denied": True})
                return "Denied."
        except KeyboardInterrupt:
            if log_tool_call: log_tool_call("shell", False, {"denied": True})
            return "Denied."

    effective_cmd = cmd
    if remote:
        sudo_cmd, _ = sudo_cache.wrap_sudo_cmd(cmd, remote)

        # Base64-encode the entire command (including any sudo wrapper) so it
        # survives the SSH transport without any quoting / escaping headaches.
        # The remote side decodes and pipes to bash.
        encoded = base64.b64encode(sudo_cmd.encode()).decode()
        shell_cmd = (
            f"ssh -o ConnectTimeout=10 {remote} "
            f"'echo {encoded} | base64 -d | bash'"
        )
    else:
        shell_cmd = cmd

    lines, rcode = stream_command_output(shell_cmd, "90m", cwd=cwd, sandbox=sandbox, timeout=timeout)
    out = "\n".join(lines)

    if len(lines) > 1000:
        _, tmp = tempfile.mkstemp(prefix="localagent_sh_", suffix=".txt", text=True)
        Path(tmp).write_text(out, encoding="utf-8")
        out = f"...\n[Output truncated. Full saved to {tmp}]\n..."

    if log_tool_call:
        log_tool_call("shell", rcode == 0, {"cmd": cmd})
    return f"Command: {cmd}\nExit Code: {rcode}\nOutput:\n{out}"