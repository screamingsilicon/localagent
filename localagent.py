from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from config import _Config
from token_counter import count_tokens, count_tokens_messages
from llm_client import llm_request
from action_parser import parse_xml_actions
from shell_executor import (
    stream_command_output, execute_shell,
    _SudoCache, run_command, is_safe_read_command,
)
from file_editor import execute_edit, execute_write
from session_manager import SessionManager
from context_manager import compress_context


APP_NAME = "localagent"

_log = logging.getLogger(APP_NAME)


# ── Turn-level behaviour knobs ────────────────────────────────────────
_TURN_TIMEOUT              = 600   # seconds before a turn is auto-aborted
_MAX_ITERATIONS            = 50    # max LLM round-trips per user request
_CONTEXT_OVERFLOW_RATIO    = 0.92  # force-compact when context exceeds this fraction of window
_CONTEXT_COMPRESS_RATIO    = 0.65  # soft-compact above this fraction
_MAX_NO_ACTION_NUDGES      = 3     # nudges before giving up on actionless responses
_MAX_CONSECUTIVE_ERRORS    = 5     # hard-stop after this many errors in a row

# ── Lazy docker_sandbox loader ────────────────────────────────────────
_docker_sandbox_module = None


def _get_docker_sandbox():
    """Return the docker_sandbox module, lazily imported."""
    global _docker_sandbox_module  # noqa: PLW0603
    if _docker_sandbox_module is None:
        try:
            import docker_sandbox as ds  # noqa: PLC0415
            _docker_sandbox_module = ds
        except ImportError:
            pass
    return _docker_sandbox_module


def _run_in_container(cmd: str, timeout: int = 10) -> str:
    """Run a command inside the sandbox container and return stdout.

    Logs a warning on any failure instead of silently returning "".
    """
    import subprocess
    ds = _get_docker_sandbox()
    if ds is None:
        _log.warning("docker_sandbox not available for _run_in_container")
        return ""
    container = ds.get_container_name()
    if not container:
        _log.warning("No container name available for _run_in_container")
        return ""
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", container, "sh", "-c", cmd],
            capture_output=True, text=True, timeout=timeout, bufsize=0,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        _log.warning("docker exec timed out (%ds): %s", timeout, cmd[:80])
        return ""
    except Exception as exc:
        _log.warning("docker exec failed for '%s': %s", cmd[:80], exc)
        return ""


def _container_system_info() -> dict[str, Any]:
    """Collect system info from inside the sandbox container in one batch call.

    Uses null-byte delimited output to avoid delimiter collision with command output.
    """
    probe = (
        'set -euo pipefail; '
        'printf "%s\\0%s\\0%s\\0%s\\0%s\\0%s\\0%s\\0" '
        '"$(uname -r 2>/dev/null || echo unknown)" '
        '"$(python3 --version 2>&1 || echo unknown)" '
        '"${SHELL:-/bin/sh}" '
        '"$(id -un 2>/dev/null || id -u 2>/dev/null || echo unknown)" '
        '"$(nproc 2>/dev/null || echo 0)" '
        '"$(head -1 /proc/meminfo 2>/dev/null || true)" '
        '"$(which git node npm jq rg fd sqlite3 cmake patch diff 2>/dev/null || true)"'
    )
    raw = _run_in_container(probe, timeout=5)
    if not raw:
        _log.warning("Container system info probe returned empty output")
        return {"os": "Linux (Docker sandbox)", "release": "unknown", "python": "unknown",
                "cwd": "/workspace", "shell": "/bin/sh", "user": "unknown", "cpu_cores": 0}

    # Split on null bytes; filter empty entries from trailing null
    parts = [p for p in raw.split("\x00") if p]
    while len(parts) < 7:
        parts.append("")

    release, python_ver, shell, user, cores_str, mem_line, tools_raw = (
        parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
    )
    shell = shell or "/bin/sh"
    cpu_cores = int(cores_str) if cores_str.strip().isdigit() else 0

    info: dict[str, Any] = {
        "os": "Linux (Docker sandbox)",
        "release": release.strip(),
        "python": python_ver.strip() or "unknown",
        "cwd": "/workspace",
        "shell": shell,
        "user": user.strip(),
        "cpu_cores": cpu_cores,
    }

    # Parse memory
    if mem_line:
        try:
            m_parts = mem_line.split()
            kb = int(m_parts[1])
            info["memory_total_gb"] = round(kb / (1024 * 1024), 1)
        except Exception:
            pass

    # Parse available tools
    known_tools = {"git", "node", "npm", "jq", "rg", "fd", "sqlite3", "cmake", "patch", "diff"}
    if tools_raw:
        found = {t.split("/")[-1] for t in tools_raw.splitlines() if t.strip()}
        available = sorted(known_tools & found)
        if available:
            info["available_tools"] = available

    return info


def system_summary() -> dict[str, Any]:
    """Return a JSON-serializable system info dict.

    When running in sandbox mode, queries the container for its actual
    environment instead of reporting host information.
    """
    import platform
    import sys as _sys

    if _Config.sandbox():
        if _get_docker_sandbox() is not None:
            return _container_system_info()

    cwd = os.getcwd()
    sum_d = {
        "os": platform.system(),
        "release": platform.release(),
        "python": sys.version.split()[0],
        "cwd": cwd,
        "shell": os.environ.get("SHELL", ""),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "cpu_cores": os.cpu_count() or 0,
    }
    if platform.system() == "Linux":
        try:
            sum_d["memory_total_gb"] = round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024**3), 1)
        except Exception:
            pass
    return sum_d


class LocalAgent:
    """Main agent orchestrator – ties together all modules."""

    def __init__(self, auto_mode: bool = False, sandbox: bool = False):
        self.auto_mode = auto_mode
        self.sandbox = sandbox
        self.cwd = "/workspace" if sandbox else os.getcwd()

        # Session / logging — allow user to override log path via --session-log
        session_log_path = _Config.session_log_path()
        self._session_mgr = SessionManager(self.cwd, log_path=session_log_path)

        # Build system prompt
        sys_prompt = _Config.system_prompt()
        _loaded_agents: list[str] = []

        # Agent instruction files: use --agents-file if provided, else scan defaults
        agent_files = _Config.agents_files()
        if agent_files:
            # User explicitly specified file(s); ignore default AGENTS.md scanning
            for fp in agent_files:
                p = Path(fp)
                if p.exists():
                    fname = p.name
                    sys_prompt += f"\n\n### {fname} ({p})\n{p.read_text('utf-8').strip()}"
                    _loaded_agents.append(str(p))
                else:
                    _log.warning("Agents file not found, skipping: %s", fp)
        else:
            # Default behaviour: scan for AGENTS.md in cwd and ~/.localagent/
            for p in [Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"]:
                if p.exists():
                    sys_prompt += f"\n\n### AGENTS.md ({p})\n{p.read_text('utf-8').strip()}"
                    _loaded_agents.append(str(p))
        if _loaded_agents:
            _log.info("Loaded %d agent instruction file(s): %s", len(_loaded_agents), _loaded_agents)

        # Conversation state
        self.messages = [{"role": "system", "content": sys_prompt}]
        self.pending_notes: list[str] = []
        self._compaction_summary = ""
        self._initial_context_sent = False
        self._repl_nudged = False

        # Sudo password cache (for remote SSH)
        self._sudo_cache = _SudoCache()

        # Load session from JSONL path if --load-session was specified
        load_path = _Config.load_session_path()
        if load_path:
            try:
                loaded = self._session_mgr.load_session_from_path(load_path)
                self.messages.extend(loaded)
                self._initial_context_sent = True
                print(f"\033[32mLoaded {len(loaded)} messages from {load_path}\033[0m")
            except FileNotFoundError:
                print(f"\033[31mSession file not found: {load_path}\033[0m")

    # -- Logging helpers (delegate to SessionManager) -------------------------

    def log_message(self, role: str, content: str):
        self._session_mgr.log_message(role, content)

    def log_tool_call(self, tool: str, success: bool, meta: dict = None):
        self._session_mgr.log_tool_call(tool, success, meta or {})

    def list_sessions(self):
        return self._session_mgr.list_sessions()

    # -- LLM ------------------------------------------------------------------

    def llm_request(self, msgs: list[dict[str, Any]], stream: bool = False) -> dict[str, Any] | None:
        return llm_request(msgs, stream=stream)

    # -- Shell helpers --------------------------------------------------------

    def stream_command_output(self, exec_cmd: str, color_code: str = "90m") -> tuple[list[str], int]:
        return stream_command_output(exec_cmd, color_code=color_code, cwd=self.cwd, sandbox=self.sandbox)

    # -- Action execution -----------------------------------------------------

    def execute_shell_action(self, act: dict[str, Any]) -> str:
        return execute_shell(act, self.auto_mode, self.cwd, self.sandbox, self._sudo_cache, self.log_tool_call)

    def execute_edit_action(self, act: dict[str, Any]) -> str:
        return execute_edit(act, self.cwd, self.auto_mode, self.sandbox, self.log_tool_call)

    def execute_write_action(self, act: dict[str, Any]) -> str:
        return execute_write(act, self.cwd, self.auto_mode, self.sandbox, self.log_tool_call)

    # -- Context management ---------------------------------------------------

    def compress_context(self):
        self.messages, self._compaction_summary = compress_context(
            self.messages, self._compaction_summary, config=_Config, llm_request_fn=self.llm_request
        )

    # -- Context guards -------------------------------------------------------

    def _estimate_tokens(self) -> int:
        """Rough token estimate for the current message list."""
        return count_tokens_messages(self.messages)

    def _ensure_context_fits(self):
        """Force-compress if context is dangerously close to the window limit."""
        ctx_window = _Config.context_window()
        if self._estimate_tokens() > int(ctx_window * _CONTEXT_OVERFLOW_RATIO):
            _log.warning("Context near overflow (%d / %d tokens), force-compacting",
                         self._estimate_tokens(), ctx_window)
            self.compress_context()

    def _maybe_compress_context(self):
        """Compress only when context exceeds the configured threshold."""
        ctx_window = _Config.context_window()
        if self._estimate_tokens() > int(ctx_window * _CONTEXT_COMPRESS_RATIO):
            self.compress_context()

    # -- Main agent loop ------------------------------------------------------

    def run_agent_turn(self, req: str):
        if not self._initial_context_sent:
            sys_info = system_summary()
            info_lines = [f"{k}: {v}" for k, v in sys_info.items()]
            req = f"### System\n" + "\n".join(info_lines) + f"\n\n{req}"
            self._initial_context_sent = True

        if self.pending_notes:
            req = "### Extra Context\n" + "\n\n".join(self.pending_notes) + f"\n\n### Request\n{req}"
            self.pending_notes.clear()

        self.messages.append({"role": "user", "content": req})
        self.log_message("user", req)

        NO_ACTION_NUDGE = (
            "You did not include any action tags. Please wrap your actions in XML:\n"
            "<shell>command</shell>\n"
            '<edit path="file.py">\n'
            "  <find>...old text...</find>\n"
            "  <replace>...new text...</replace>\n"
            "</edit>\n"
            '<write path="file.py">content</write>\n'
            "If you are done, reply with <done/>."
        )
        self._repl_nudged = False

        consecutive_no_action = 0
        consecutive_errors = 0
        
        # Turn-level timeout guard (10 minutes)
        turn_start = time.monotonic()
        
        for iteration in range(_MAX_ITERATIONS):
            if time.monotonic() - turn_start > _TURN_TIMEOUT:
                print("\n\033[33m⚠ Turn timed out after 10 minutes. Moving on.\033[0m")
                break

            try:
                # Context window overflow protection
                self._ensure_context_fits()

                if not (resp := self.llm_request(self.messages, stream=True)):
                    break

                text = resp.get("content", "")
                self.messages.append({"role": "assistant", "content": text})
                self.log_message("assistant", text)

                u, t = resp.get("usage", {}), resp.get("timings", {})
                if u and t:
                    print(f"\033[90mctx: {(u.get('prompt_tokens', 0) / _Config.context_window()) * 100:.1f}% | cache: {(t.get('cache_n', 0) / max(u.get('prompt_tokens', 1), 1)) * 100:.0f}% | {t.get('predicted_per_second', 0):.1f} t/s\033[0m")
                elif u:
                    print(f"\033[90mctx: {(u.get('prompt_tokens', 0) / _Config.context_window()) * 100:.1f}%\033[0m")

                actions = parse_xml_actions(text)

                if not actions:
                    if "<done" in text or "<done/>" in text:
                        break

                    # In non-auto (REPL) mode, nudge once then return to user
                    if not self.auto_mode:
                        if not self._repl_nudged:
                            self._repl_nudged = True
                            print(f"\n\033[90m⚡ No actions found — asking agent to retry...\033[0m")
                            self.messages.append({"role": "user", "content": NO_ACTION_NUDGE})
                            continue
                        break

                    consecutive_no_action += 1
                    if consecutive_no_action > _MAX_NO_ACTION_NUDGES:
                        print(f"\n\033[33m⚠ Model didn't produce any actions after {_MAX_NO_ACTION_NUDGES} nudges. Moving on.\033[0m")
                        break
                    print(f"\n\033[90m⚡ Nudge ({consecutive_no_action}/{_MAX_NO_ACTION_NUDGES}): model produced no actions, retrying...\033[0m")
                    self.messages.append({"role": "user", "content": NO_ACTION_NUDGE})
                    continue

                consecutive_no_action = 0
                print()
                results = []
                for a in actions:
                    if a["type"] == "shell":
                        results.append(self.execute_shell_action(a))
                    elif a["type"] == "edit":
                        results.append(self.execute_edit_action(a))
                    elif a["type"] == "error":
                        consecutive_errors += 1
                        results.append(f"\033[31m[Parse Error]\033[0m {a['message']}")
                    else:
                        results.append(self.execute_write_action(a))

                if consecutive_errors > _MAX_CONSECUTIVE_ERRORS:
                    print(f"\n\033[33m⚠ Too many consecutive errors ({_MAX_CONSECUTIVE_ERRORS}). Giving up.\033[0m")
                    break

                self.messages.append({"role": "user", "content": "### Action Results\n\n" + "\n\n---\n\n".join(results)})
                # Only compact when context is getting large
                self._maybe_compress_context()

            except KeyboardInterrupt:
                print(f"\n\033[33m⚠ Turn interrupted (Ctrl+C). Session preserved. Type a new request or /exit.\033[0m")
                if self.messages and self.messages[-1].get("role") == "user":
                    self.messages.pop()
                self._session_mgr.log_event("turn_interrupted")
                break
            except Exception as exc:
                _log.exception("Error in agent turn – feeding back to LLM")
                error_msg = f"\033[31m[Error]\033[0m {exc}"
                print(f"\n{error_msg}")
                self._session_mgr.log_event("turn_error", extra={"detail": str(exc)})

                consecutive_errors += 1
                if consecutive_errors > _MAX_CONSECUTIVE_ERRORS:
                    print(f"\n\033[33m⚠ Too many consecutive errors ({_MAX_CONSECUTIVE_ERRORS}). Giving up.\033[0m")
                    break

                # Feed the error back to the LLM so it can self-correct
                err_feedback = f"Your previous response caused an error:\n\n```\n{exc}\n```\n\nPlease fix the issue and try again."
                self.messages.append({"role": "user", "content": err_feedback})

    # -- REPL entry point -----------------------------------------------------

    def run_repl(self):
        from repl import run_repl as _run_repl
        _run_repl(self)


# -- Entry point --------------------------------------------------------------

if __name__ == "__main__":
    if _Config.sandbox():
        import docker_sandbox
        docker_sandbox.setup_sandbox(cpus=_Config.cpus(), memory=_Config.memory())

    agent = LocalAgent(auto_mode=_Config.auto_mode(), sandbox=_Config.sandbox())

    if _Config.task():
        agent.run_agent_turn(_Config.task())
    else:
        agent.run_repl()