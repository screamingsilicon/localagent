from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from config import _Config, _get_args
from llm_client import llm_request, _model_tag
from action_parser import parse_xml_actions
from shell_executor import (
    stream_command_output, execute_shell,
    _SudoCache, run_command, is_safe_read_command,
)
from file_editor import execute_edit, execute_write
from display import set_terminal_title
from session_manager import SessionManager
from context_manager import compress_context


APP_NAME = "localagent"


def system_summary() -> dict[str, Any]:
    """Return a JSON-serializable system info dict."""
    import platform
    import sys

    cwd = "/workspace" if _Config.sandbox() else os.getcwd()
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

        # Session / logging
        self._session_mgr = SessionManager(self.cwd)

        # Build system prompt
        sys_prompt = _Config.system_prompt()
        for p in [Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"]:
            if p.exists():
                sys_prompt += f"\n\n### AGENTS.md\n{p.read_text('utf-8').strip()}"
                break

        # Conversation state
        self.messages = [{"role": "system", "content": sys_prompt}]
        self.pending_notes: list[str] = []
        self._compaction_summary = ""
        self._initial_context_sent = False

        # Sudo password cache (for remote SSH)
        self._sudo_cache = _SudoCache()

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

    # -- Main agent loop ------------------------------------------------------

    def run_agent_turn(self, req: str):
        if not self._initial_context_sent:
            req = f"### System\n{json.dumps(system_summary())}\n\n{req}"
            self._initial_context_sent = True

        if self.pending_notes:
            req = "### Extra Context\n" + "\n\n".join(self.pending_notes) + f"\n\n### Request\n{req}"
            self.pending_notes.clear()

        self.messages.append({"role": "user", "content": req})
        self.log_message("user", req)

        NO_ACTION_NUDGE = "You didn't include any action tags (<shell>, <edit>, or <write>). If you are done, reply with <done/> otherwise continue."
        max_nudges = 3
        consecutive_no_action = 0

        for _ in range(50):
            try:
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

                clean_text = re.sub(r'', '', text)
                actions = parse_xml_actions(clean_text)

                if not actions:
                    if "<done" in clean_text or "<done/>" in clean_text:
                        break

                    consecutive_no_action += 1
                    if consecutive_no_action > max_nudges:
                        print(f"\n\033[33m⚠ Model didn't produce any actions after {max_nudges} nudges. Moving on.\033[0m")
                        break
                    print(f"\n\033[90m⚡ Nudge ({consecutive_no_action}/{max_nudges}): model produced no actions, retrying...\033[0m")
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
                    else:
                        results.append(self.execute_write_action(a))

                self.messages.append({"role": "user", "content": "### Action Results\n\n" + "\n\n---\n\n".join(results)})
                self.compress_context()

            except KeyboardInterrupt:
                print(f"\n\033[33m⚠ Turn interrupted (Ctrl+C). Session preserved. Type a new request or /exit.\033[0m")
                if self.messages and self.messages[-1].get("role") == "user":
                    self.messages.pop()
                self._session_mgr._write_log({"type": "event", "ts": time.time(), "event": "turn_interrupted"})
                break

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