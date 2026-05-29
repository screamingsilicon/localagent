#!/usr/bin/env python3
from __future__ import annotations

import ast
import atexit
import base64
import difflib
import getpass
import json
import os
import platform
import random
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import urllib.request

# =========================================================================
# CLI Argument Parsing
# =========================================================================

CLI_VERSION = 5

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        prog="localagent",
        description="localagent – AI-powered terminal agent for shell execution, file editing, and writing.",
        epilog="Examples:\n  %(prog)s                      Start interactive REPL\n  %(prog)s --yolo                 Start in auto-execute mode\n  %(prog)s --sandbox              Run inside a secure Docker sandbox\n  %(prog)s \"fix the auth bug\"     One-shot: run a task and exit\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-y", "--yolo", action="store_true", help="Enable auto-execute mode (skip y/n confirmations)")
    parser.add_argument("--sandbox", action="store_true", help="Launch the agent in an isolated Docker container")
    parser.add_argument("--host", default=None, help="LLM host URL (overrides LLM_HOST env var)")
    parser.add_argument("--model", default=None, help="Model name (overrides LLM_MODEL env var)")
    parser.add_argument("--temperature", type=float, default=None, help="Temperature for LLM responses (overrides LLM_TEMPERATURE env var)")
    parser.add_argument("--n-ctx", type=int, default=None, help="Context window size (overrides LLM_N_CTX env var)")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s v{CLI_VERSION}")
    parser.add_argument("task", nargs="?", default=None, help="One-shot task: run it and exit")
    return parser.parse_args()

# =========================================================================
# Constants, Theme & UI Configuration
# =========================================================================

_ARGS = parse_args()
AUTO_MODE = _ARGS.yolo
APP_NAME = "localagent"
LLM_HOST = _ARGS.host or os.getenv("LLM_HOST", "http://localhost:8080")
MODEL = _ARGS.model or os.getenv("LLM_MODEL", "local-model")
TEMPERATURE = _ARGS.temperature if _ARGS.temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.7"))
HTTP_REQUEST_TIMEOUT = 600

# --- Dynamic context sizing (fetched from /v1/models at startup) ---
# Percentages of the model's actual n_ctx
_COMPRESS_PCT      = 0.50   # light compression kicks in at 50%
_SUMMARIZE_PCT     = 0.70   # full summarization at 70%
_TURN_PREFIX_PCT   = 0.20   # keep last 20% of context after summarization
_MAX_TOKENS_PCT    = 0.85   # leave 15% headroom for the model's response

# Defaults when /v1/models returns no meta
_FALLBACK_N_CTX = 90000
_FALLBACK_MODEL_TAG = ""


def _extract_quant(model_id: str) -> str:
    """Pull a quant tag like Q6_K_XL from a model ID."""
    m = re.search(r'(Q\d+_[A-Z0-9_]+(?:\.\d+)?)', model_id)
    return m.group(1) if m else ""


def _fetch_model_info():
    """Query /v1/models, return (n_ctx, model_id, quant_tag).
    Retries on transient network/DNS errors (common in Docker sandbox
    where the proxy container's DNS entry may not be ready yet)."""
    req = urllib.request.Request(
        f"{LLM_HOST}/v1/models",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    retries = 5
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.URLError as e:
            if attempt == retries:
                raise
            wait = 1.0 * attempt  # 1s, 2s, 3s ...
            print(f"[!] /v1/models unreachable (attempt {attempt}/{retries}): {e.reason}. Retrying in {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
    else:
        return _FALLBACK_N_CTX, _FALLBACK_MODEL_TAG, ""

    n_ctx = _FALLBACK_N_CTX
    model_id, quant_tag = _FALLBACK_MODEL_TAG, ""
    for m in data.get("data", []):
        ctx = (m.get("meta", {}).get("n_ctx")
               or m.get("meta", {}).get("n_ctx_train")
               or None)
        if ctx:
            n_ctx = int(ctx)
        mid = m.get("id", "")
        if mid:
            model_id = mid
            quant_tag = _extract_quant(mid)
            break
    return n_ctx, model_id, quant_tag


def _resolve_context_limits():
    """Query /v1/models for n_ctx, derive all token thresholds as percentages."""
    n_ctx, model_id, quant_tag = _fetch_model_info()
    n_ctx = _ARGS.n_ctx or int(os.getenv("LLM_N_CTX", n_ctx))  # CLI arg or env override possible

    context_window     = n_ctx
    max_tokens         = int(n_ctx * _MAX_TOKENS_PCT)
    compress_threshold = int(n_ctx * _COMPRESS_PCT)
    summarize_threshold = int(n_ctx * _SUMMARIZE_PCT)
    turn_prefix_tokens = int(n_ctx * _TURN_PREFIX_PCT)

    return context_window, max_tokens, compress_threshold, summarize_threshold, turn_prefix_tokens, model_id, quant_tag


CONTEXT_WINDOW, MAX_TOKENS, LOCALAGENT_COMPRESS_THRESHOLD, LOCALAGENT_SUMMARIZE_THRESHOLD, LOCALAGENT_TURN_PREFIX_TOKENS, _MODEL_ID, _MODEL_QUANT = _resolve_context_limits()


def _model_tag() -> str:
    """Build a compact model tag like 'unsloth/Qwen3.6-27B-MTP-GGUF (Q6_K_XL) - 128k ctx'."""
    if not _MODEL_ID:
        return ""
    name = _MODEL_ID.split(":")[0]
    tag = f"{name} ({_MODEL_QUANT})" if _MODEL_QUANT else name
    return f"{tag} - {CONTEXT_WINDOW // 1000}k ctx"

MAX_FILE_SIZE = 256 * 1024

RESET, BOLD, ITALIC, STRIKE, CLEAR_LINE = "\033[0m", "\033[1m", "\033[3m", "\033[9m", "\033[K"
H1_COLOR, H2_COLOR, H3_COLOR = "\033[1;4;38;5;213m", "\033[1;38;5;213m", "\033[1;38;5;177m"
CODE_BG, XML_BG = "\033[48;5;236;38;5;253m", "\033[48;5;129;38;5;255m"
QUOTE_COLOR, LIST_BULLET, TABLE_BORDER = "\033[38;5;245;3m", "\033[38;5;214m", "\033[38;5;239m"
LINK_TEXT, LINK_URL = "\033[38;5;111;4m", "\033[38;5;240m"

XML_SYSTEM_PROMPT = """You are an advanced AI agent. You control the host machine using precise XML tags. Do NOT use JSON-based tool calls.

## Available Tools

1. Shell Execution (`<shell>`)
- Local machine: `<shell>command</shell>`
- Remote host through SSH: `<shell remote="user@host">command</shell>`

When using 'sudo' over SSH, sudo auth will be handled by the user or automatically.

2. Surgical File Edits (`<edit>`)
Use exact text matching (including whitespace).

Local:

<edit path="file.py">
<find>
old code here
</find>
<replace>
new code here
</replace>
</edit>

Remote SSH:

<edit path="file.py" remote="user@host">
<find>
old code here
</find>
<replace>
new code here
</replace>
</edit>

3. New File Creation (`<write>`)

Local:

<write path="new_file.py">
content here
</write>

Remote SSH:

<write path="new_file.py" remote="user@host">
content here
</write>

For <shell> tags: only one per response. Wait for the result before running the next shell command.
You may include multiple <edit> and/or <write> tags in a single response.
"""

_SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Produce a structured summary of the conversation history.
Format exactly as follows:
## 1. Long-Term Goals
## 2. Short-Term Goals
## 3. Key Decisions & Rationale
## 4. Key Artifacts & Modifications
## 5. Previous Attempts & Failures
## 6. Current State of Ongoing Work
## 7. Next Steps
"""

# =========================================================================
# Utilities & Heuristics
# =========================================================================

def format_relative_time(ts: float) -> str:
    diff = time.time() - ts
    for unit, limit in [("d", 86400), ("h", 3600), ("m", 60)]:
        if diff >= limit: return f"{int(diff // limit)}{unit} ago"
    return "just now"

def is_safe_read_command(cmd: str) -> bool:
    safe_bins = {"cat", "sed", "head", "tail", "wc", "grep", "find", "ls", "pwd", "echo", "date", "file", "which"}
    dang_pats = {"| rm", "xargs rm", "| sh", "| bash", ">", "; rm", "; mv", "&& rm", "`", "$("}
    
    c = cmd.strip()
    words = c.split()
    if not words or words[0] not in safe_bins or any(p in c for p in dang_pats): return False
    if words[0] == "sed" and "-i" in c: return False
    if words[0] == "find" and any(f in c for f in ("-exec", "-delete")): return False
    return True

def check_syntax(path: str, content: str) -> tuple[bool, str | None]:
    if not path.endswith(".py"): return True, None
    try: ast.parse(content); return True, None
    except SyntaxError as e: return False, str(e)

def system_summary() -> dict[str, Any]:
    sum_d = {"os": platform.system(), "release": platform.release(), "python": sys.version.split()[0], "cwd": os.getcwd(), "shell": os.environ.get("SHELL", ""), "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")), "cpu_cores": os.cpu_count() or 0}
    if platform.system() == "Linux":
        try: sum_d["memory_total_gb"] = round(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / (1024**3), 1)
        except: pass
    return sum_d

def run_command(cmd: str) -> str | None:
    try: return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except Exception: return None

_TMUX_WINDOW_ID = run_command("tmux display-message -p '#{window_id}' 2>/dev/null")

def set_terminal_title(t: str) -> None:
    print(f"\033]0;{t}\007", end="", flush=True)
    if _TMUX_WINDOW_ID: run_command(f"tmux rename-window -t {_TMUX_WINDOW_ID} {t!r} 2>/dev/null")

# =========================================================================
# Filesystem & IO Wrappers
# =========================================================================

def read_file(path: str, base_dir: str, remote: str | None = None, allow_escape: bool = False) -> tuple[str | None, str | None]:
    if remote:
        p = subprocess.run(f"ssh {remote} \"cat '{path}'\"", shell=True, capture_output=True, text=True)
        return (p.stdout, None) if p.returncode == 0 else (None, p.stderr.strip())
    try:
        p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
        base_resolved = Path(base_dir).resolve()
        if not allow_escape and not p.is_relative_to(base_resolved): return None, "path_escapes"
        if not p.exists(): return None, "not found"
        if p.is_symlink():
            resolved_link = p.resolve()
            if not allow_escape and not resolved_link.is_relative_to(base_resolved):
                return None, "symlink escapes repo boundary"
        if not stat.S_ISREG(p.stat().st_mode): return None, "not a regular file"
        if p.stat().st_size > MAX_FILE_SIZE: return None, "file too large"
        content = p.read_text(encoding="utf-8")
        return content if content else "[empty]", None
    except UnicodeDecodeError: return None, "binary/not UTF-8"
    except Exception as e: return None, str(e)

def write_file(path: str, content: str, base_dir: str, remote: str | None = None, allow_escape: bool = False) -> str | None:
    if remote:
        tmp = f"{path}.tmp.{random.randint(100000, 999999)}"
        p = subprocess.run(
            f"ssh {remote} \"cat > '{tmp}' && mv '{tmp}' '{path}'\"",
            shell=True, input=content, text=True, capture_output=True,
        )
        return p.stderr.strip() if p.returncode != 0 else None
    try:
        p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
        base_resolved = Path(base_dir).resolve()
        if not allow_escape and not p.is_relative_to(base_resolved): return "path_escapes"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return None
    except Exception as e: return str(e)

# =========================================================================
# Text & XML Parsing
# =========================================================================

def normalize_text(text: str, strict: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict: return text
    text = "\n".join(line.rstrip() for line in unicodedata.normalize("NFKC", text).split("\n"))
    for pat, rep in [(r"[\u2018\u2019\u201a\u201b]", "'"), (r"[\u201c\u201d\u201e\u201f]", '"'), (r"[\u2010-\u2015\u2212]", "-"), (r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ")]:
        text = re.sub(pat, rep, text)
    return text

def find_and_replace(content: str, old_text: str, new_text: str, path: str, strict: bool = False) -> tuple[str, str]:
    if not old_text: raise ValueError("oldText empty")
    if (exact_idx := content.find(old_text)) != -1:
        if content.count(old_text) > 1: raise ValueError("Multiple exact matches found.")
        return content, content[:exact_idx] + new_text + content[exact_idx + len(old_text):]

    if strict:
        raise ValueError(f"Text not found in {path}. Provide an exact match (including whitespace/indentation).")
    base, norm_old = normalize_text(content), normalize_text(old_text)
    if (norm_idx := base.find(norm_old)) == -1: raise ValueError(f"Text not found in {path}. Check whitespace/indentation.")
    if base.count(norm_old) > 1: raise ValueError("Multiple fuzzy matches found.")
    return base, base[:norm_idx] + new_text + base[norm_idx + len(norm_old):]

def format_diff(old_str: str, new_str: str, ctx: int = 1) -> str:
    diff = difflib.unified_diff(old_str.splitlines(), new_str.splitlines(), n=ctx, lineterm="")
    return "\n".join(f" {RESET} ..." if l.startswith("@@") else l for l in diff if not l.startswith(("---", "+++")))

def parse_xml_actions(text: str) -> list[dict[str, Any]]:
    actions = []
    pattern = r'<(?P<tag>shell|edit|write)(?:[^>]*path="(?P<path>[^"]+)")?(?:[^>]*remote="(?P<remote>[^"]+)")?[^>]*>(?P<inner>[\s\S]*?)</\1>'
    for m in re.finditer(pattern, text):
        tag, inner = m.group("tag"), m.group("inner")
        act = {"type": tag, "remote": m.group("remote"), "path": m.group("path") or ""}
        if tag == "shell": act["command"] = inner.strip()
        elif tag == "write": act["content"] = inner.strip()
        elif tag == "edit":
            find_m = re.search(r'<find>([\s\S]*?)</find>', inner)
            rep_m = re.search(r'<replace>([\s\S]*?)</replace>', inner)
            act["find"] = find_m.group(1).strip('\n') if find_m else ""
            act["replace"] = rep_m.group(1).strip('\n') if rep_m else ""
        actions.append(act)
    return actions

# =========================================================================
# Markdown & Visuals
# =========================================================================

def format_inline_markdown(text: str, restore: str = RESET) -> str:
    ph = {}
    _m = lambda prefix: f"\x01{prefix}{len(ph)}\x04"

    text = re.sub(r'(</?(?:shell|edit|find|replace|write)\b[^>]*>)', lambda m: ph.setdefault(_m("XML"), f"{XML_BG}{m.group(1)}{restore}"), text)
    text = re.sub(r'(?<!`)`([^`\n]+)`(?!`)', lambda m: ph.setdefault(_m("CODE"), f"{CODE_BG}{m.group(1)}{restore}"), text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', lambda m: ph.setdefault(_m("LNK"), f"\033]8;;{m.group(2)}\033\\{LINK_TEXT}{m.group(1)}{restore}\033]8;;\033\\"), text)

    for pat, style in [(r'\*\*(.+?)\*\*', BOLD), (r'__(.+?)__', BOLD), (r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', ITALIC), (r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', ITALIC), (r'~~(.+?)~~', STRIKE)]:
        text = re.sub(pat, lambda m: f"{style}{m.group(1)}{restore}", text)

    for k in reversed(list(ph.keys())): text = text.replace(k, ph[k])
    return text

def render_md(text: str) -> str:
    res, w = [], shutil.get_terminal_size((80, 20)).columns
    for part in re.split(r"(```[\s\S]*?```)", text):
        if part.startswith("```"):
            lines = part[3:-3].strip().split('\n')
            if lines and lines[0].strip().isalnum(): lines = lines[1:]
            res.extend(["", *(f"{CODE_BG}{l.ljust(w)}{CLEAR_LINE}{RESET}" for l in lines), ""])
        else:
            for l in part.split('\n'):
                s = l.strip()
                if l.startswith('# '): res.append(f"{H1_COLOR}{format_inline_markdown(l[2:], H1_COLOR)}{RESET}")
                elif l.startswith('## '): res.append(f"{H2_COLOR}{format_inline_markdown(l[3:], H2_COLOR)}{RESET}")
                elif l.startswith('### '): res.append(f"{H3_COLOR}{format_inline_markdown(l[4:], H3_COLOR)}{RESET}")
                elif l.startswith('> '): res.append(f"{QUOTE_COLOR}▌ {format_inline_markdown(l[2:], QUOTE_COLOR)}{RESET}")
                elif m := re.match(r'^(\s*)[*+-]\s+(.*)', l): res.append(f"{m.group(1)}{LIST_BULLET}•{RESET} {format_inline_markdown(m.group(2))}")
                elif m := re.match(r'^(\s*\d+)\.\s+(.*)', l): res.append(f"{LIST_BULLET}{m.group(1)}.{RESET} {format_inline_markdown(m.group(2))}")
                elif re.match(r'^[\s]*([-*_])\1{2,}\s*$', s): res.append(f"{TABLE_BORDER} {'─' * (w - 2)} {RESET}")
                else: res.append(format_inline_markdown(l))
    return re.sub(r'\n{3,}', '\n\n', "\n".join(res)).strip()

class Spinner:
    def __init__(self): self.stop_event = threading.Event()
    def start(self):
        def spin():
            i = 0
            while not self.stop_event.is_set():
                print(f"\r\033[90m{"|/-\\"[i % 4]} \033[0m", end="", flush=True); i += 1; time.sleep(0.1)
        threading.Thread(target=spin, daemon=True).start()
    def stop(self): self.stop_event.set(); print(f"\r{CLEAR_LINE}", end="", flush=True)

# =========================================================================
# Core Agent & Operations
# =========================================================================

class LocalAgent:
    def __init__(self, auto_mode: bool = False):
        self.auto_mode = auto_mode
        self.cwd = os.getcwd()
        self.log_dir = Path.home() / ".localagent" / "logs" / Path(self.cwd).name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.log_dir / f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._write_log({"type": "session", "cwd": self.cwd, "started_at": time.time()})

        sys_prompt = XML_SYSTEM_PROMPT
        for p in [Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"]:
            if p.exists(): sys_prompt += f"\n\n### AGENTS.md\n{p.read_text('utf-8').strip()}"; break

        self.messages, self.pending_notes, self._compaction_summary, self._initial_context_sent = [{"role": "system", "content": sys_prompt}], [], "", False
        self._sudo_password_cache: dict[str, str] = {}

    def _get_sudo_password(self, remote: str) -> str | None:
        """Retrieve or prompt for a cached sudo password for a remote host."""
        encoded = self._sudo_password_cache.get(remote)
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
        self._sudo_password_cache[remote] = base64.b64encode(pw.encode()).decode()
        return pw

    def _write_log(self, rec: dict):
        with open(self.session_file, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    def log_message(self, r: str, c: str): self._write_log({"type": "message", "ts": time.time(), "role": r, "content": c})
    def log_tool_call(self, t: str, s: bool, m: dict = {}): self._write_log({"type": "tool", "ts": time.time(), "tool": t, "success": s, **m})

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for p in sorted(self.log_dir.glob("*.jsonl"), reverse=True):
            meta = {"id": p.stem, "started_at": p.stat().st_mtime, "last_message_at": p.stat().st_mtime, "messages": 0, "last_user_message": None}
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines: continue
                try: 
                    first = json.loads(lines[0])
                    if first.get("type") == "session": meta["started_at"] = first.get("started_at", meta["started_at"])
                except: pass
                for line in lines:
                    if '"type": "message"' in line:
                        meta["messages"] += 1
                        if '"role": "user"' in line:
                            try: meta["last_user_message"] = json.loads(line)
                            except: pass
            sessions.append(meta)
        return sessions

    def llm_request(self, msgs: list[dict[str, Any]]) -> dict[str, Any] | None:
        req = urllib.request.Request(f"{LLM_HOST}/v1/chat/completions", headers={"Content-Type": "application/json"}, data=json.dumps({"model": MODEL, "messages": msgs, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "cache_prompt": True}).encode())
        spin = Spinner(); spin.start()
        try:
            with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as r: return json.loads(r.read().decode())
        except KeyboardInterrupt: raise
        except Exception as e: print(f"\033[31m[API Error: {e}]\033[0m"); return None
        finally: spin.stop()

    def stream_command_output(self, exec_cmd: str, color_code: str = "90m") -> tuple[list[str], int]:
        p = subprocess.Popen(exec_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=self.cwd)
        lines = []
        try:
            for l in p.stdout:
                print(f"\033[{color_code}{l.rstrip()}\033[0m" if color_code else l, end="" if not color_code else "\n")
                lines.append(l.rstrip('\n'))
            p.wait()
        except KeyboardInterrupt:
            p.terminate()
            try: p.wait(timeout=2)
            except: p.kill()
            lines.append("[Interrupted]")
        return lines, p.returncode

    def _wrap_sudo_cmd(self, cmd: str, remote: str) -> tuple[str, str]:
        """If cmd contains sudo and we have a password, wrap with sudo -S.
        Returns (effective_cmd_for_ssh, cmd_to_log_and_display)."""
        if not re.search(r'(^|\s|;|&&|\|\|)sudo\b', cmd):
            return cmd, cmd
        pw = self._get_sudo_password(remote)
        if pw is None:
            return cmd, cmd  # fall through, let it fail
        escaped_pw = pw.replace("'", "'\\''")
        wrapped = f"echo '{escaped_pw}' | sudo -S {cmd}"
        return wrapped, cmd

    def execute_shell(self, act: dict[str, Any]) -> str:
        cmd, remote = act["command"], act["remote"]
        safe = is_safe_read_command(cmd) and not remote
        print(f"\033[{'90m' if safe else '36m'}{f'[{remote}] ' if remote else ''}$ {cmd}\033[0m")
        
        if not safe and not self.auto_mode:
            print(f"{BOLD}(y/n): {RESET}", end="", flush=True)
            try: 
                if input().strip().lower() != 'y': self.log_tool_call("shell", False, {"denied": True}); return "Denied."
            except KeyboardInterrupt: self.log_tool_call("shell", False, {"denied": True}); return "Denied."

        effective_cmd = cmd
        if remote:
            sudo_cmd, _ = self._wrap_sudo_cmd(cmd, remote)
            escaped_cmd = sudo_cmd.replace("\\", "\\\\").replace('"', '\\"')
            shell_cmd = f"ssh -o ConnectTimeout=10 {remote} \"{escaped_cmd}\""
        else:
            shell_cmd = cmd

        lines, rcode = self.stream_command_output(shell_cmd, "90m")
        out = "\n".join(lines)

        if len(lines) > 1000:
            _, tmp = tempfile.mkstemp(prefix="localagent_sh_", suffix=".txt", text=True)
            Path(tmp).write_text(out, encoding="utf-8")
            out = f"...\n[Output truncated. Full saved to {tmp}]\n..."
            
        self.log_tool_call("shell", rcode == 0, {"cmd": cmd})
        return f"Command: {cmd}\nExit Code: {rcode}\nOutput:\n{out}"

    def _is_path_escape(self, path: str) -> bool:
        """Check if the given path resolves outside of self.cwd."""
        try:
            resolved = Path(self.cwd, Path(path).expanduser()).resolve()
            return not resolved.is_relative_to(Path(self.cwd).resolve())
        except Exception:
            return False

    def execute_edit(self, act: dict[str, Any]) -> str:
        path, rem, f_txt, r_txt = act["path"], act["remote"], act["find"], act["replace"]

        # First try read with normal boundaries
        content, err = read_file(path, self.cwd, rem)
        if err == "path_escapes":
            # Path is outside cwd — prompt for approval
            escape_path = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"\033[33m⚠ [Edit] Path escapes repo boundary: {escape_path}\033[0m")

            # Try reading with allow_escape to show the diff
            content, err = read_file(path, self.cwd, rem, allow_escape=True)
            if err:
                self.log_tool_call("edit", False, {"err": err}); return f"Error reading {path}: {err}"

            try:
                base, new = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
                if not (ok := check_syntax(path, new))[0]:
                    self.log_tool_call("edit", False, {"err": ok[1]}); return f"Syntax Error: {ok[1]}"

                diff = format_diff(base, new)
                print(f"\033[36mProposed changes:\033[0m")
                for l in diff.splitlines(): print(f"\033[{'32m' if l.startswith('+') else '31m' if l.startswith('-') else '90m'}{l}\033[0m")

                if not self.auto_mode:
                    print(f"{BOLD}(Approve? y/n): {RESET}", end="", flush=True)
                    try:
                        if input().strip().lower() != 'y':
                            self.log_tool_call("edit", False, {"denied": True, "path": path})
                            return "Denied by user."
                    except KeyboardInterrupt:
                        self.log_tool_call("edit", False, {"denied": True, "path": path}); return "Denied by user."

                if err := write_file(path, new, self.cwd, rem, allow_escape=True):
                    self.log_tool_call("edit", False, {"err": err}); return f"Write failed: {err}"
            except Exception as e:
                self.log_tool_call("edit", False, {"err": str(e)}); return f"Edit failed: {e}"

        elif err:
            self.log_tool_call("edit", False, {"err": err}); return f"Error reading {path}: {err}"

        else:
            try:
                base, new = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
                if not (ok := check_syntax(path, new))[0]:
                    self.log_tool_call("edit", False, {"err": ok[1]}); return f"Syntax Error: {ok[1]}"

                diff = format_diff(base, new)
                print(f"\033[36m[Edit] {rem or 'local'} -> {path}\033[0m")
                for l in diff.splitlines(): print(f"\033[{'32m' if l.startswith('+') else '31m' if l.startswith('-') else '90m'}{l}\033[0m")

                if err := write_file(path, new, self.cwd, rem):
                    self.log_tool_call("edit", False, {"err": err}); return f"Write failed: {err}"
            except Exception as e:
                self.log_tool_call("edit", False, {"err": str(e)}); return f"Edit failed: {e}"

        self.log_tool_call("edit", True, {"path": path})
        return f"Successfully edited {path}\n\nDiff:\n{diff}"

    def execute_write(self, act: dict[str, Any]) -> str:
        path, rem, content = act["path"], act["remote"], act["content"]
        if not path: return "Error: missing 'path'."
        if not (ok := check_syntax(path, content))[0]:
            self.log_tool_call("write", False, {"err": ok[1], "path": path}); return f"Syntax Error: {ok[1]}"

        # Check if path escapes repo boundary
        if self._is_path_escape(path):
            escape_path = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"\033[33m⚠ [Write] Path escapes repo boundary: {escape_path}\033[0m")
            print(f"\033[36mProposed file content ({len(content.splitlines())} lines):\033[0m")
            for l in content.splitlines()[:10]: print(f"\033[32m+{l}\033[0m")
            if len(content.splitlines()) > 10: print(f"\033[32m... ({len(content.splitlines()) - 10} more lines)\033[0m")

            if not self.auto_mode:
                print(f"{BOLD}(Approve? y/n): {RESET}", end="", flush=True)
                try:
                    if input().strip().lower() != 'y':
                        self.log_tool_call("write", False, {"denied": True, "path": path})
                        return "Denied by user."
                except KeyboardInterrupt:
                    self.log_tool_call("write", False, {"denied": True, "path": path}); return "Denied by user."

            if err := write_file(path, content, self.cwd, rem, allow_escape=True):
                self.log_tool_call("write", False, {"err": err}); return f"Write failed: {err}"
        else:
            if err := write_file(path, content, self.cwd, rem):
                self.log_tool_call("write", False, {"err": err}); return f"Write failed: {err}"

            print(f"\033[36m[Write] {rem or 'local'} -> {path}\033[0m")
            for l in content.splitlines()[:10]: print(f"\033[32m+{l}\033[0m")
            if len(content.splitlines()) > 10: print(f"\033[32m... ({len(content.splitlines())} lines written)\033[0m")

        self.log_tool_call("write", True, {"path": path})
        return f"Wrote content to {path}"

    def compress_context(self):
        est = lambda msgs: sum(len(m.get("content", "")) // 4 for m in msgs)
        if est(self.messages) > LOCALAGENT_COMPRESS_THRESHOLD:
            for m in self.messages:
                if m["role"] == "user" and "### Action Results" in m["content"]:
                    m["content"] = f"{m['content'][:500]}\n...[Compressed]...\n{m['content'][-500:]}"

        if est(self.messages) > LOCALAGENT_SUMMARIZE_THRESHOLD:
            acc, split_idx = 0, 1
            for i in range(len(self.messages) - 1, -1, -1):
                if (acc := acc + len(self.messages[i].get("content", "")) // 4) > LOCALAGENT_TURN_PREFIX_TOKENS: split_idx = max(1, i); break
            
            if split_idx >= len(self.messages) - 1: return
            p = "Summarize:\n" + "\n".join(f"[{m['role']}]\n{m['content']}" for m in self.messages[1:split_idx])
            if self._compaction_summary: p = f"Prev summary:\n{self._compaction_summary}\n\nNew:\n{p}"
            
            if resp := self.llm_request([{"role": "system", "content": _SUMMARIZATION_SYSTEM_PROMPT}, {"role": "user", "content": p}]):
                self._compaction_summary = resp["choices"][0]["message"].get("content", "")
                self.messages = [self.messages[0], {"role": "assistant", "content": f"Memory Summary:\n{self._compaction_summary}"}] + self.messages[split_idx:]

    def run_agent_turn(self, req: str):
        if not self._initial_context_sent:
            req = f"### System\n{json.dumps(system_summary())}\n\n{req}"; self._initial_context_sent = True
        if self.pending_notes:
            req = "### Extra Context\n" + "\n\n".join(self.pending_notes) + f"\n\n### Request\n{req}"
            self.pending_notes.clear()

        self.messages.append({"role": "user", "content": req}); self.log_message("user", req)

        for _ in range(50):
            try:
                if not (resp := self.llm_request(self.messages)): break

                text = resp["choices"][0]["message"].get("content", "")
                self.messages.append({"role": "assistant", "content": text}); self.log_message("assistant", text)

                if reason := re.search(r'<think>([\s\S]*?)</think>', text) or resp["choices"][0]["message"].get("reasoning_content"):
                    print(f"\033[3;90m{(reason.group(1) if isinstance(reason, re.Match) else reason).strip()}\033[0m\n")

                if clean := re.sub(r'<think>[\s\S]*?</think>\n*', '', text).strip(): print(render_md(clean))

                u, t = resp.get("usage", {}), resp.get("timings", {})
                if u and t:
                    print(f"\033[90mctx: {(u.get('prompt_tokens', 0) / CONTEXT_WINDOW) * 100:.1f}% | cache: {(t.get('cache_n', 0) / u.get('prompt_tokens', 1)) * 100:.0f}% | {t.get('predicted_per_second', 0):.1f} t/s\033[0m")

                if not (actions := parse_xml_actions(text)): break
                print()
                self.messages.append({"role": "user", "content": "### Action Results\n\n" + "\n\n---\n\n".join(
                    self.execute_shell(a) if a["type"] == "shell" else self.execute_edit(a) if a["type"] == "edit" else self.execute_write(a) for a in actions
                )})
                self.compress_context()
            except KeyboardInterrupt:
                print(f"\n\033[33m⚠ Turn interrupted (Ctrl+C). Session preserved. Type a new request or /exit.\033[0m")
                self.messages.pop()
                self._write_log({"type": "event", "ts": time.time(), "event": "turn_interrupted"})
                break

    def run_repl(self):
        global LLM_HOST
        tag = f"  \033[90m{ _model_tag() }\033[0m" if _model_tag() else ""
        print(f"\033[36m{APP_NAME} @ {LLM_HOST}{tag}{f' \033[31m[YOLO: ON]\033[0m' if self.auto_mode else ''} (/help)\033[0m")
        while True:
            set_terminal_title(f"❓ {APP_NAME}"); print(f"\n\033[32m❯ \033[0m", end="", flush=True)
            try: lines = [input()]
            except EOFError: break
            except KeyboardInterrupt: print("\n[Interrupted]"); continue
            while True:
                try: lines.append(input())
                except EOFError: break
                except KeyboardInterrupt: break
            
            if not (ui := "\n".join(lines).strip()): continue
            
            if ui.startswith("!"):
                out_lines, _ = self.stream_command_output(ui[1:].strip(), "")
                try:
                    if input("\n\aAdd to context? [y/N]: ").strip().lower() == 'y':
                        self.pending_notes.append(f"$ {ui[1:].strip()}\n" + "\n".join(out_lines[-100:]))
                        print(f"\033[32mAdded to context.\033[0m")
                except KeyboardInterrupt: pass
            elif ui.startswith("/"):
                cmd, _, arg = ui.partition(" ")
                if cmd in ("/exit", "/quit"): break
                elif cmd == "/help":
                    print(f"{H2_COLOR}Available Commands:{RESET}\n  {BOLD}!cmd{RESET}       Run `cmd` locally and optionally add output to context\n  {BOLD}/sessions{RESET}  List recent conversation sessions\n  {BOLD}/load <id>{RESET} Load a previous session by its number or ID\n  {BOLD}/clear{RESET}     Clear conversation history (keeps system prompt)\n  {BOLD}/auto{RESET}      Toggle auto-execute mode\n  {BOLD}/host URL{RESET}  Change LLM host\n  {BOLD}/exit{RESET}      Quit the agent")
                elif cmd == "/sessions":
                    print(f"\033[36mRecent conversations:\033[0m")
                    for i, s in enumerate(self.list_sessions()[:10], 1):
                        prv = ((re.search(r"### Request\n(.+)", c := s["last_user_message"].get("content", ""), re.S).group(1) if re.search(r"### Request\n(.+)", c, re.S) else c[:60]).replace("\n", " ")[:47] + "...") if s.get("last_user_message") else ""
                        print(f" {i}. \033[36m{format_relative_time(s['last_message_at'])}\033[0m ({s['messages']} msgs)\n    \"{prv}\"")
                elif cmd == "/clear":
                    self.messages = [self.messages[0]]
                    self._initial_context_sent = False
                    print("\033[32mConversation cleared.\033[0m")
                elif cmd == "/auto":
                    self.auto_mode = not self.auto_mode
                    print(f"\033[32mAuto-execute mode: {'ON' if self.auto_mode else 'OFF'}\033[0m")
                elif cmd == "/host":
                    new_host = arg.strip()
                    if not new_host:
                        print(f"\033[90mCurrent LLM host: {LLM_HOST}\033[0m")
                    else:
                        LLM_HOST = new_host
                        print(f"\033[32mLLM host changed to: {LLM_HOST}\033[0m")
                elif cmd == "/load":
                    s_id = (s := self.list_sessions())[int(arg.strip()) - 1]["id"] if arg.strip().isdigit() and 0 <= int(arg.strip()) - 1 < len(s) else arg.strip()
                    try:
                        self.messages = [self.messages[0]] + [json.loads(l) for l in open(self.log_dir / f"{s_id}.jsonl") if '"type": "message"' in l and json.loads(l)["role"] != "system"]
                        self._initial_context_sent, msg = True, f"\033[32mLoaded {len(self.messages)-1} messages.\033[0m"
                    except: msg = f"\033[31mSession not found.\033[0m"
                    print(msg)
            else:
                set_terminal_title(f"⏳ {APP_NAME}")
                try: self.run_agent_turn(ui)
                except KeyboardInterrupt: print(f"\n\033[33m⚠ Turn interrupted (Ctrl+C). Session preserved. Type a new request or /exit.\033[0m")
        print("\nGoodbye!"); set_terminal_title("")

# =========================================================================
# Docker Sandbox Orchestration
# =========================================================================

def _ensure_socat_proxy_image():
    if subprocess.run(["docker", "image", "inspect", "socat-proxy"], capture_output=True).returncode == 0:
        return
    print("[*] Building socat-proxy image...")
    subprocess.run(
        ["docker", "build", "-t", "socat-proxy", "-"],
        input="FROM alpine\nRUN apk add --no-cache socat\nENTRYPOINT [\"socat\"]\n",
        text=True, check=True, capture_output=True,
    )


def ensure_docker_image():
    if subprocess.run(["docker", "image", "inspect", "localagent-image"], capture_output=True).returncode == 0: return
    print("[*] Docker image 'localagent-image' not found. Building it automatically...")
    try:
        subprocess.run(["docker", "build", "-t", "localagent-image", "-"], input="FROM python:3.12-alpine\nRUN apk add --no-cache git tmux\nWORKDIR /workspace\n", text=True, check=True, capture_output=True)
        print("[*] Image built successfully!\n")
    except subprocess.CalledProcessError:
        print("[!] Error: Failed to build the Docker image. Ensure Docker is running.")
        sys.exit(1)

def resolve_target_ip(hostname: str) -> str:
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", hostname): return hostname
    try:
        if (ip := socket.gethostbyname(hostname)) != "127.0.0.1": return ip
    except: pass
    print(f"[!] Error: Could not resolve IP for host '{hostname}'.\n[!] Ensure the host is accessible on your network.")
    sys.exit(1)

def launch_in_docker(args_to_pass: list[str]):
    ensure_docker_image()
    _ensure_socat_proxy_image()
    parsed = urlparse(os.environ.get("LLM_HOST", LLM_HOST))
    tgt_host, tgt_port = parsed.hostname or "localhost", parsed.port or 8080

    if tgt_host in ("localhost", "127.0.0.1"):
        print(f"[!] Warning: LLM_HOST targets '{tgt_host}'. Inside Docker, use LAN/VPN IP instead.")

    print(f"[*] Analyzing LLM_HOST: {parsed.geturl()}")
    ip = resolve_target_ip(tgt_host)
    print(f"[*] Resolved '{tgt_host}' to {ip}")

    net, proxy = "agent-sandbox", f"llm-proxy-{random.randint(10000, 99999)}"
    atexit.register(lambda: (subprocess.run(["docker", "rm", "-f", proxy], capture_output=True), subprocess.run(["docker", "network", "rm", net], capture_output=True)))

    print("[*] Setting up sandboxed environment...")
    subprocess.run(["docker", "network", "rm", net], capture_output=True)
    subprocess.run(["docker", "network", "create", "--internal", net], check=True, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--rm", "--name", proxy, "--network", "bridge", "socat-proxy", f"TCP-LISTEN:{tgt_port},fork,reuseaddr", f"TCP:{ip}:{tgt_port}"], check=True, capture_output=True)
    subprocess.run(["docker", "network", "connect", net, proxy], check=True, capture_output=True)

    c_host = f"{parsed.scheme or 'http'}://{proxy}:{tgt_port}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")
    cmd = [
        "docker", "run", "--rm", "-it", "--network", net, "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp",
        "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp", "-v", f"{os.getcwd()}:/workspace:rw",
        "-v", f"{os.path.abspath(__file__)}:/app/localagent.py:ro", "-w", "/workspace", "-e", f"LLM_HOST={c_host}",
        "localagent-image", "python", "/app/localagent.py"
    ] + args_to_pass

    print(f"[*] Launching agent. Internal LLM_HOST mapped to {c_host}\n")
    try: subprocess.run(cmd)
    except KeyboardInterrupt: pass
    sys.exit(0)

# =========================================================================
# Main Execution
# =========================================================================

if __name__ == "__main__":
    if _ARGS.sandbox:
        f_args = sys.argv[1:]
        if "--sandbox" in f_args: f_args.remove("--sandbox")
        launch_in_docker(f_args)
    else:
        agent = LocalAgent(auto_mode=AUTO_MODE)
        if _ARGS.task:
            agent.run_agent_turn(_ARGS.task)
        else:
            agent.run_repl()
