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
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

from render_markdown import render_md, MD_BLANK, _is_md_list_item
from highlighters import highlight_bash
import urllib.request



CLI_VERSION = 5

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        prog="localagent",
        description="localagent – AI-powered terminal agent for shell execution, file editing, and writing.",
        epilog="Examples:\n  %(prog)s                Start interactive REPL\n  %(prog)s --yolo                 Start in auto-execute mode\n  %(prog)s --sandbox              Run inside a secure Docker sandbox\n  %(prog)s \"fix the auth bug\"     One-shot: run a task and exit\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-y", "--yolo", action="store_true", help="Enable auto-execute mode (skip y/n confirmations)")
    parser.add_argument("--sandbox", action="store_true", help="Launch the agent in an isolated Docker container")
    parser.add_argument("--cpus", type=float, default=2.0, help="Limit CPU cores for sandbox (default: 2, e.g. 2 or 0.5)")
    parser.add_argument("--memory", type=str, default='4g', help="Limit memory for sandbox (default: 4g, e.g. '4g', '512m')")
    parser.add_argument("--host", default=None, help="LLM host URL (overrides LLM_HOST env var)")
    parser.add_argument("--model", default=None, help="Model name (overrides LLM_MODEL env var)")
    parser.add_argument("--temperature", type=float, default=None, help="Temperature for LLM responses (overrides LLM_TEMPERATURE env var)")
    parser.add_argument("--n-ctx", type=int, default=None, help="Context window size (overrides LLM_N_CTX env var)")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s v{CLI_VERSION}")
    parser.add_argument("task", nargs="?", default=None, help="One-shot task: run it and exit")
    return parser.parse_args()


_ARGS = parse_args()
AUTO_MODE = _ARGS.yolo
APP_NAME = "localagent"
LLM_HOST = _ARGS.host or os.getenv("LLM_HOST", "http://localhost:8080")
MODEL = _ARGS.model or os.getenv("LLM_MODEL", "local-model")
TEMPERATURE = _ARGS.temperature if _ARGS.temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.7"))
HTTP_REQUEST_TIMEOUT = 600


_COMPRESS_PCT      = 0.50
_SUMMARIZE_PCT     = 0.70
_TURN_PREFIX_PCT   = 0.20
_MAX_TOKENS_PCT    = 0.85

_FALLBACK_N_CTX = 90000
_FALLBACK_MODEL_TAG = ""


def _extract_quant(model_id: str) -> str:
    m = re.search(r'(Q\d+_[A-Z0-9_]+(?:\.\d+)?)', model_id)
    return m.group(1) if m else ""


def _fetch_model_info():
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
            wait = 1.0 * attempt
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
    try:
        n_ctx, model_id, quant_tag = _fetch_model_info()
    except Exception:
        n_ctx, model_id, quant_tag = _FALLBACK_N_CTX, _FALLBACK_MODEL_TAG, ""
    
    n_ctx = _ARGS.n_ctx or int(os.getenv("LLM_N_CTX", n_ctx))

    context_window     = n_ctx
    max_tokens         = int(n_ctx * _MAX_TOKENS_PCT)
    compress_threshold = int(n_ctx * _COMPRESS_PCT)
    summarize_threshold = int(n_ctx * _SUMMARIZE_PCT)
    turn_prefix_tokens = int(n_ctx * _TURN_PREFIX_PCT)

    return context_window, max_tokens, compress_threshold, summarize_threshold, turn_prefix_tokens, model_id, quant_tag


CONTEXT_WINDOW, MAX_TOKENS, LOCALAGENT_COMPRESS_THRESHOLD, LOCALAGENT_SUMMARIZE_THRESHOLD, LOCALAGENT_TURN_PREFIX_TOKENS, _MODEL_ID, _MODEL_QUANT = _resolve_context_limits()


def _model_tag() -> str:
    if not _MODEL_ID:
        return ""
    name = _MODEL_ID.split(":")[0]
    tag = f"{name} ({_MODEL_QUANT})" if _MODEL_QUANT else name
    return f"{tag} - {CONTEXT_WINDOW // 1000}k ctx"

MAX_FILE_SIZE = 256 * 1024

RESET, BOLD, ITALIC, STRIKE, CLEAR_LINE = "\033[0m", "\033[1m", "\033[3m", "\033[9m", "\033[K"
THINK_COLOR = "\033[3;90m"
INLINE_CODE_BG = "\033[48;5;238m"
H1_COLOR, H2_COLOR, H3_COLOR = "\033[1;4;38;5;213m", "\033[1;38;5;213m", "\033[1;38;5;177m"
CODE_BG, XML_BG = "\033[48;5;236;38;5;253m", "\033[48;5;129;38;5;255m"
QUOTE_COLOR, LIST_BULLET, TABLE_BORDER = "\033[38;5;245;3m", "\033[38;5;214m", "\033[38;5;239m"
LINK_TEXT, LINK_URL = "\033[38;5;111;4m", "\033[38;5;240m"
SHELL_OUTPUT_BG = "\033[48;5;235;90m"  # faint dark bg + dim gray text

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

For <shell> tags: use at most one per reply. Wait for the result before running the next shell command.
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
    cwd = "/workspace" if _ARGS.sandbox else os.getcwd()
    sum_d = {"os": platform.system(), "release": platform.release(), "python": sys.version.split()[0], "cwd": cwd, "shell": os.environ.get("SHELL", ""), "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")), "cpu_cores": os.cpu_count() or 0}
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


def read_file(path: str, base_dir: str, remote: str | None = None, allow_escape: bool = False) -> tuple[str | None, str | None]:
    if remote:
        p = subprocess.run(f"ssh {remote} \"cat '{path}'\"", shell=True, capture_output=True, text=True)
        return (p.stdout, None) if p.returncode == 0 else (None, p.stderr.strip())

    if _ARGS.sandbox:
        try:
            p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
            base_resolved = Path(base_dir).resolve()
            if not allow_escape and not p.is_relative_to(base_resolved): return None, "path_escapes"
        except Exception:
            pass
        resolved = Path(path).resolve(strict=False)
        rel = os.path.relpath(resolved, "/workspace")
        cpath = f"/workspace/{rel}"
        content, err = _docker_exec_read_file(cpath)
        if err: return None, "not found"
        if not content: return "[empty]", None
        return content, None

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

    if _ARGS.sandbox:
        try:
            p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
            base_resolved = Path(base_dir).resolve()
            if not allow_escape and not p.is_relative_to(base_resolved): return "path_escapes"
        except Exception:
            pass
        resolved = Path(path).resolve(strict=False)
        rel = os.path.relpath(resolved, "/workspace")
        cpath = f"/workspace/{rel}"
        subprocess.run(["docker", "exec", "-i", _SANDBOX_CONTAINER, "sh", "-c", f"mkdir -p '{os.path.dirname(cpath)}'"], capture_output=True)
        rc = _docker_exec_file_write(cpath, content)
        return None if rc == 0 else "write failed"

    try:
        p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
        base_resolved = Path(base_dir).resolve()
        if not allow_escape and not p.is_relative_to(base_resolved): return "path_escapes"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return None
    except Exception as e: return str(e)


def normalize_text(text: str, strict: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict: return text
    text = "\n".join(line.rstrip() for line in unicodedata.normalize("NFKC", text).split("\n"))
    for pat, rep in [(r"[\u2018\u2019\u201a\u201b]", "'"), (r"[\u201c\u201d\u201e\u201f]", '"'), (r"[\u2010-\u2015\u2212]", "-"), (r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " ")]:
        text = re.sub(pat, rep, text)
    return text

def find_and_replace(content: str, old_text: str, new_text: str, path: str, strict: bool = False) -> tuple[str, str, int, int]:
    """Returns (old_content, new_content, start_line, end_line) using 1-based line numbers."""
    if not old_text: raise ValueError("oldText empty")
    if (exact_idx := content.find(old_text)) != -1:
        if content.count(old_text) > 1: raise ValueError("Multiple exact matches found.")
        start_line = content[:exact_idx].count('\n') + 1
        end_line = content[exact_idx:exact_idx + len(old_text)].count('\n') + start_line
        return content, content[:exact_idx] + new_text + content[exact_idx + len(old_text):], start_line, end_line

    if strict:
        raise ValueError(f"Text not found in {path}. Provide an exact match (including whitespace/indentation).")
    base, norm_old = normalize_text(content), normalize_text(old_text)
    if (norm_idx := base.find(norm_old)) == -1: raise ValueError(f"Text not found in {path}. Check whitespace/indentation.")
    if base.count(norm_old) > 1: raise ValueError("Multiple fuzzy matches found.")
    start_line = base[:norm_idx].count('\n') + 1
    end_line = base[norm_idx:norm_idx + len(norm_old)].count('\n') + start_line
    return base, base[:norm_idx] + new_text + base[norm_idx + len(norm_old):], start_line, end_line

def format_diff(old_str: str, new_str: str, ctx: int = 1) -> str:
    diff = difflib.unified_diff(old_str.splitlines(), new_str.splitlines(), n=ctx, lineterm="")
    return "\n".join(f" {RESET} ..." if l.startswith("@@") else l for l in diff if not l.startswith(("---", "+++")))


def _get_highlighter(path: str):
    """Return a highlight function based on file extension, or None."""
    ext = os.path.splitext(path)[1].lower()
    lang_map = {
        ".py": "python",
        ".pyi": "python",
        ".sh": "bash",
        ".bash": "bash",
        ".html": "html",
        ".htm": "html",
    }
    lang = lang_map.get(ext)
    if not lang:
        return None
    try:
        from highlighters import get_highlighter
        hl_fn, _ = get_highlighter(lang)
        return hl_fn
    except (KeyError, ImportError):
        return None


def _print_highlighted_content(content: str, path: str, prefix: str = "+", max_lines: int = 10) -> None:
    """Print file content with syntax highlighting if available, or plain green fallback."""
    hl_fn = _get_highlighter(path)
    lines = content.splitlines()

    if hl_fn is not None:
        highlighted = hl_fn(content)
        for i, line in enumerate(highlighted.splitlines()):
            if max_lines and i >= max_lines:
                break
            print(f"\033[32m{prefix}{RESET}{line}\033[0m")
    else:
        for i, line in enumerate(lines):
            if max_lines and i >= max_lines:
                break
            print(f"\033[32m{prefix}{line}\033[0m")

    if max_lines and len(lines) > max_lines:
        print(f"\033[90m... ({len(lines) - max_lines} more lines)\033[0m")

def parse_xml_actions(text: str) -> list[dict[str, Any]]:
    actions = []
    
    # (?m) enables multiline mode (^ and $ match start/end of lines)
    # Branch 1: <shell> allows inline or multiline anywhere.
    # Branch 2: <edit> and <write> STRICTLY require opening and closing tags to be at the start of a line.
    pattern = (
        r'(?m)'
        r'<(shell)\b([^>]*)>([\s\S]*?)</\1>|'
        r'^[ \t]*<(edit|write)\b(?=[^>]*\bpath="[^"]+")([^>]*)>\n([\s\S]*?)\n^[ \t]*</\4>'
    )
    
    for m in re.finditer(pattern, text):
        if m.group(1):
            tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        else:
            tag, attrs, inner = m.group(4), m.group(5), m.group(6)
            
        path_m = re.search(r'\bpath="([^"]+)"', attrs)
        remote_m = re.search(r'\bremote="([^"]+)"', attrs)
        
        act = {
            "type": tag,
            "remote": remote_m.group(1) if remote_m else None,
            "path": path_m.group(1) if path_m else ""
        }
        
        if tag == "shell":
            act["command"] = inner.strip()
        elif tag == "write":
            act["content"] = inner.strip()
        elif tag == "edit":
            # Also strictly anchor <find> and <replace> to avoid nested collisions
            find_m = re.search(r'(?m)^[ \t]*<find>\n([\s\S]*?)\n^[ \t]*</find>', inner)
            rep_m = re.search(r'(?m)^[ \t]*<replace>\n([\s\S]*?)\n^[ \t]*</replace>', inner)
            act["find"] = find_m.group(1).strip('\n') if find_m else ""
            act["replace"] = rep_m.group(1).strip('\n') if rep_m else ""
            
        actions.append(act)
        
    return actions

class Spinner:
    def __init__(self): self.stop_event = threading.Event()
    def start(self):
        def spin():
            i = 0
            while not self.stop_event.is_set():
                print(f"\r\033[90m{"|/-\\"[i % 4]} \033[0m", end="", flush=True); i += 1; time.sleep(0.1)
        threading.Thread(target=spin, daemon=True).start()
    def stop(self): self.stop_event.set(); print(f"\r{CLEAR_LINE}", end="", flush=True)


class LocalAgent:
    def __init__(self, auto_mode: bool = False, sandbox: bool = False):
        self.auto_mode = auto_mode
        self.sandbox = sandbox
        self.cwd = "/workspace" if sandbox else os.getcwd()
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
    
    def llm_request(self, msgs: list[dict[str, Any]], stream: bool = False) -> dict[str, Any] | None:
        payload = {
            "model": MODEL,
            "messages": msgs,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "cache_prompt": True
        }
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}

        req = urllib.request.Request(
            f"{LLM_HOST}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode()
        )
        
        spin = Spinner()
        spin.start()
        
        try:
            if not stream:
                with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as r:
                    spin.stop()
                    return json.loads(r.read().decode())
            else:
                with urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as r:
                    spin.stop()
                    
                    full_text = ""
                    usage_data = {}
                    timing_data = {}
                    in_native_think = False
                    in_simulated_think = False
                    raw_buffer = ""
                    md_buffer = ""

                    _prev_was = {"type": "other"}

                    def flush_md_buffer():
                        nonlocal md_buffer
                        while md_buffer:
                            s_stripped = md_buffer.lstrip(" \t\r\n")
                            if not s_stripped:
                                break

                            block_found = False
                            is_buffering_xml = False

                            for tag in ["write", "edit", "shell"]:
                                start_sig = f"<{tag}"
                                end_sig = f"</{tag}>"

                                if s_stripped.startswith(start_sig):
                                    end_idx = md_buffer.find(end_sig)
                                    if end_idx != -1:
                                        block_len = end_idx + len(end_sig)
                                        block = md_buffer[:block_len]
                                        md_buffer = md_buffer[block_len:]
                                        rendered = render_md(block)
                                        if rendered:
                                            print(rendered)
                                        _prev_was["type"] = "other"
                                        block_found = True
                                        break
                                    else:
                                        is_buffering_xml = True
                                        break
                                elif start_sig.startswith(s_stripped):
                                    is_buffering_xml = True
                                    break

                            if block_found:
                                continue

                            if is_buffering_xml:
                                return

                            if "\n" in md_buffer:
                                line_end = md_buffer.find("\n")
                                line = md_buffer[:line_end]
                                md_buffer = md_buffer[line_end + 1:]

                                rendered = render_md(line)

                                if rendered is MD_BLANK:
                                    _prev_was["type"] = "blank"
                                    continue

                                if not rendered:
                                    continue

                                prev = _prev_was["type"]
                                cur_is_header = line.startswith("# ") or line.startswith("## ") or line.startswith("### ")
                                cur_is_list = _is_md_list_item(line.lstrip()) if not cur_is_header else False

                                if cur_is_header:
                                    print()
                                elif prev in ("header", "blank") and not cur_is_list:
                                    print()
                                elif prev == "list" and not cur_is_list:
                                    print()

                                print(rendered)

                                if cur_is_header:
                                    _prev_was["type"] = "header"
                                elif cur_is_list:
                                    _prev_was["type"] = "list"
                                else:
                                    _prev_was["type"] = "other"
                                continue

                            break 
                    
                    for line in r:
                        line = line.decode('utf-8').strip()
                        if not line or line.startswith(":"):
                            continue
                        if line == "data: [DONE]":
                            break
                        if line.startswith("data: "):
                            try:
                                chunk = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue

                            if "usage" in chunk and chunk["usage"]:
                                usage_data = chunk["usage"]
                            if "timings" in chunk and chunk["timings"]:
                                timing_data = chunk["timings"]
                            
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                                
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            
                            if reasoning:
                                if not in_native_think:
                                    print("\n" + THINK_COLOR + "> ", end="", flush=True)
                                    in_native_think = True
                                    full_text += "<think>\n"
                                print(reasoning, end="", flush=True)
                                full_text += reasoning
                                
                            if in_native_think and content:
                                print(RESET + "\n", end="", flush=True)
                                in_native_think = False
                                full_text += "\n</think>\n"
                                
                            if content:
                                full_text += content
                                raw_buffer += content
                                
                                while raw_buffer:
                                    if not in_simulated_think:
                                        if "<think>" in raw_buffer:
                                            before, _, after = raw_buffer.partition("<think>")
                                            if before:
                                                md_buffer += before
                                                flush_md_buffer()
                                            print("\n" + THINK_COLOR + "> ", end="", flush=True)
                                            in_simulated_think = True
                                            raw_buffer = after
                                        else:
                                            last_open = raw_buffer.rfind("<")
                                            if last_open != -1 and not raw_buffer.endswith(">") and "think".startswith(raw_buffer[last_open+1:]):
                                                md_buffer += raw_buffer[:last_open]
                                                raw_buffer = raw_buffer[last_open:]
                                                break 
                                            else:
                                                md_buffer += raw_buffer
                                                raw_buffer = ""
                                                flush_md_buffer()
                                    else:
                                        if "</think>" in raw_buffer:
                                            before, _, after = raw_buffer.partition("</think>")
                                            print(before, end="", flush=True)
                                            print(RESET + "\n", end="", flush=True)
                                            in_simulated_think = False
                                            raw_buffer = after
                                        else:
                                            last_open = raw_buffer.rfind("<")
                                            if last_open != -1 and not raw_buffer.endswith(">") and "/think".startswith(raw_buffer[last_open+1:]):
                                                print(raw_buffer[:last_open], end="", flush=True)
                                                raw_buffer = raw_buffer[last_open:]
                                                break
                                            else:
                                                print(raw_buffer, end="", flush=True)
                                                raw_buffer = ""
                                        
                    if in_native_think or in_simulated_think:
                        print(RESET, end="", flush=True)
                        
                    if md_buffer.strip():
                        flush_md_buffer()
                        remaining = md_buffer.strip()
                        rendered = render_md(remaining)
                        if rendered is not MD_BLANK and rendered:
                            prev = _prev_was["type"]
                            cur_is_header = remaining.startswith("# ") or remaining.startswith("## ") or remaining.startswith("### ")
                            if cur_is_header or prev in ("header", "list", "blank"):
                                print()
                            print(rendered)
                            
                    print()
                    return {"content": full_text, "usage": usage_data, "timings": timing_data}
                    
        except KeyboardInterrupt:
            spin.stop()
            raise
        except Exception as e:
            spin.stop()
            print(f"\033[31m[API Error: {e}]\033[0m")
            return None
        
    def stream_command_output(self, exec_cmd: str, color_code: str = "90m") -> tuple[list[str], int]:
        if self.sandbox:
            return _docker_exec(exec_cmd)

        p = subprocess.Popen(exec_cmd, shell=True, executable="/bin/bash", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=self.cwd)
        lines = []
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
            p.terminate()
            try: p.wait(timeout=2)
            except: p.kill()
            lines.append("[Interrupted]")
        return lines, p.returncode

    def _wrap_sudo_cmd(self, cmd: str, remote: str) -> tuple[str, str]:
        if not re.search(r'(^|\s|;|&&|\|\|)sudo\b', cmd):
            return cmd, cmd
        pw = self._get_sudo_password(remote)
        if pw is None:
            return cmd, cmd
        escaped_pw = pw.replace("'", "'\\''")
        wrapped = f"echo '{escaped_pw}' | sudo -S {cmd}"
        return wrapped, cmd

    def execute_shell(self, act: dict[str, Any]) -> str:
        cmd, remote = act["command"], act["remote"]
        safe = is_safe_read_command(cmd) and not remote
        highlighted_cmd = highlight_bash(cmd)
        prefix_color = "90m" if safe else "36m"
        remote_prefix = f"[{remote}] " if remote else ""
        print(f"\033[{prefix_color}$ {remote_prefix}\033[0m{highlighted_cmd}")
        
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
        if self.sandbox:
            return False  # No boundary checks inside sandbox — the container is the boundary
        try:
            resolved = Path(self.cwd, Path(path).expanduser()).resolve()
            return not resolved.is_relative_to(Path(self.cwd).resolve())
        except Exception:
            return False

    def execute_edit(self, act: dict[str, Any]) -> str:
        path, rem, f_txt, r_txt = act["path"], act["remote"], act["find"], act["replace"]

        content, err = read_file(path, self.cwd, rem)
        if err == "path_escapes":
            escape_path = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"\033[33m⚠ [Edit] Path escapes repo boundary: {escape_path}\033[0m")

            content, err = read_file(path, self.cwd, rem, allow_escape=True)
            if err:
                self.log_tool_call("edit", False, {"err": err}); return f"Error reading {path}: {err}"

            try:
                base, new, start_line, end_line = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
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
                n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
                n_added   = sum(1 for l in diff.splitlines() if l.startswith("+"))
                print(f"\033[36m[Edit] {rem or 'local'} -> {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines\033[0m")
            except Exception as e:
                self.log_tool_call("edit", False, {"err": str(e)}); return f"Edit failed: {e}"

        elif err:
            self.log_tool_call("edit", False, {"err": err}); return f"Error reading {path}: {err}"

        else:
            try:
                base, new, start_line, end_line = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
                if not (ok := check_syntax(path, new))[0]:
                    self.log_tool_call("edit", False, {"err": ok[1]}); return f"Syntax Error: {ok[1]}"

                diff = format_diff(base, new)
                n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
                n_added   = sum(1 for l in diff.splitlines() if l.startswith("+"))
                print(f"\033[36m[Edit] {rem or 'local'} -> {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines\033[0m")

                if err := write_file(path, new, self.cwd, rem):
                    self.log_tool_call("edit", False, {"err": err}); return f"Write failed: {err}"
            except Exception as e:
                self.log_tool_call("edit", False, {"err": str(e)}); return f"Edit failed: {e}"

        self.log_tool_call("edit", True, {"path": path})
        n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
        n_added   = sum(1 for l in diff.splitlines() if l.startswith("+"))
        return f"Successfully edited {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines"

    def execute_write(self, act: dict[str, Any]) -> str:
        path, rem, content = act["path"], act["remote"], act["content"]
        if not path: return "Error: missing 'path'."
        if not (ok := check_syntax(path, content))[0]:
            self.log_tool_call("write", False, {"err": ok[1], "path": path}); return f"Syntax Error: {ok[1]}"

        n_lines = len(content.splitlines())

        if self._is_path_escape(path):
            escape_path = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"\033[33m⚠ [Write] Path escapes repo boundary: {escape_path}\033[0m")
            print(f"\033[36mProposed file content ({n_lines} lines):\033[0m")
            _print_highlighted_content(content, path, prefix="+", max_lines=10)

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

            print(f"\033[36m[Write] Wrote {n_lines} lines to {path}\033[0m")
        else:
            if err := write_file(path, content, self.cwd, rem):
                self.log_tool_call("write", False, {"err": err}); return f"Write failed: {err}"

            print(f"\033[36m[Write] Wrote {n_lines} lines to {path}\033[0m")

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
            
            if resp := self.llm_request([{"role": "system", "content": _SUMMARIZATION_SYSTEM_PROMPT}, {"role": "user", "content": p}], stream=False):
                self._compaction_summary = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
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
                if not (resp := self.llm_request(self.messages, stream=True)): break

                text = resp.get("content", "")
                self.messages.append({"role": "assistant", "content": text}); self.log_message("assistant", text)

                u, t = resp.get("usage", {}), resp.get("timings", {})
                if u and t:
                    print(f"\033[90mctx: {(u.get('prompt_tokens', 0) / CONTEXT_WINDOW) * 100:.1f}% | cache: {(t.get('cache_n', 0) / max(u.get('prompt_tokens', 1), 1)) * 100:.0f}% | {t.get('predicted_per_second', 0):.1f} t/s\033[0m")
                elif u:
                    print(f"\033[90mctx: {(u.get('prompt_tokens', 0) / CONTEXT_WINDOW) * 100:.1f}%\033[0m")

                clean_text = re.sub(r'<think>[\s\S]*?</think>', '', text)
                if not (actions := parse_xml_actions(clean_text)): break
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
        host = re.sub(r'^https?://', '', LLM_HOST)
        model_tag = _model_tag() if _model_tag() else ""

        parts = [f"\033[1;36m⚡ {APP_NAME}\033[0m"]
        parts.append(f"\033[90m{host}\033[0m")
        if self.sandbox:
            parts.append(f"\033[33m[{_SANDBOX_CONTAINER}]\033[0m")
        if model_tag:
            parts.append(f"\033[90m│\033[0m \033[37m{model_tag}\033[0m")
        if self.auto_mode:
            parts.append(f"\033[1;31m[yolo]\033[0m")

        print(" ".join(parts) + f"  \033[90m(/help)\033[0m")
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
                    print(f"{H2_COLOR}Available Commands:{RESET}\n  {BOLD}!cmd{RESET}       Run `cmd` locally and optionally add output to context\n  {BOLD}/sessions{RESET} List recent conversation sessions\n  {BOLD}/load <id>{RESET} Load a previous session by its number or ID\n  {BOLD}/clear{RESET}     Clear conversation history (keeps system prompt)\n  {BOLD}/auto{RESET}      Toggle auto-execute mode\n  {BOLD}/host URL{RESET}  Change LLM host\n  {BOLD}/exit{RESET}      Quit the agent")
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


def ensure_docker_image():
    if subprocess.run(["docker", "image", "inspect", "localagent-image"], capture_output=True).returncode == 0: return
    print("[*] Docker image 'localagent-image' not found. Building it automatically...")
    try:
        subprocess.run(["docker", "build", "-t", "localagent-image", "-"], input="FROM python:3.12-alpine\nRUN apk add --no-cache git tmux\nWORKDIR /workspace\n", text=True, check=True, capture_output=True)
        print("[*] Image built successfully!\n")
    except subprocess.CalledProcessError:
        print("[!] Error: Failed to build the Docker image. Ensure Docker is running.")
        sys.exit(1)


_SANDBOX_CONTAINER = None


def setup_sandbox():
    """Create persistent container with no network. Agent runs on host, tools exec inside."""
    global _SANDBOX_CONTAINER

    ensure_docker_image()

    _SANDBOX_CONTAINER = f"agent-sandbox-{os.getpid()}-{int(time.time())}"

    cmd = [
        "docker", "run", "-d", "--name", _SANDBOX_CONTAINER,
        "--network", "none",
        "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp:exec",
        "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
        "-v", f"{os.getcwd()}:/workspace:rw", "-w", "/workspace",
    ]
    if _ARGS.cpus is not None:
        cmd.extend(["--cpus", str(_ARGS.cpus)])
    if _ARGS.memory is not None:
        cmd.extend(["--memory", _ARGS.memory])
    cmd.extend(["localagent-image", "tail", "-f", "/dev/null"])
    subprocess.run(cmd, check=True, capture_output=True)

    atexit.register(_teardown_sandbox)


def _teardown_sandbox():
    if _SANDBOX_CONTAINER:
        subprocess.run(["docker", "rm", "-f", _SANDBOX_CONTAINER], capture_output=True)


def _docker_exec(cmd: str, cwd: str | None = None) -> tuple[list[str], int]:
    """Execute a command inside the sandbox container, streaming output."""
    docker_cmd = ["docker", "exec", "-i", _SANDBOX_CONTAINER, "sh", "-c", cmd]
    p = subprocess.Popen(
        docker_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    lines = []
    try:
        for line in p.stdout:
            lines.append(line.rstrip('\n'))
            w = shutil.get_terminal_size((80, 20)).columns
            print(f"{SHELL_OUTPUT_BG}{line.rstrip().ljust(w)}{CLEAR_LINE}{RESET}", end="\n")
        p.wait()
    except KeyboardInterrupt:
        p.terminate()
        try: p.wait(timeout=2)
        except: p.kill()
        lines.append("[Interrupted]")
    return lines, p.returncode


def _docker_exec_file_write(path: str, content: str) -> int:
    """Write file content inside sandbox via stdin pipe."""
    p = subprocess.run(
        ["docker", "exec", "-i", _SANDBOX_CONTAINER, "sh", "-c", f"cat > '{path}'"],
        input=content, text=True, capture_output=True
    )
    return p.returncode





def _docker_exec_read_file(path: str) -> tuple[str | None, str | None]:
    """Read file content from inside sandbox container."""
    p = subprocess.run(
        ["docker", "exec", _SANDBOX_CONTAINER, "cat", path],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        return None, p.stderr.strip()
    return p.stdout, None


if __name__ == "__main__":
    if _ARGS.sandbox:
        setup_sandbox()

    agent = LocalAgent(auto_mode=AUTO_MODE, sandbox=_ARGS.sandbox)
    if _ARGS.task:
        agent.run_agent_turn(_ARGS.task)
    else:
        agent.run_repl()
