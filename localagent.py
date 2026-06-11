#!/usr/bin/env python3
"""localagent – AI-powered terminal agent for shell execution, file editing, and writing.

Single-file implementation, organized top-down:

    Config / parse_config   immutable runtime configuration (CLI flags + env vars)
    ModelInfo / ContextLimits
                            model discovery via /v1/models and derived token budgets
    Sandbox                 optional Docker container isolation for shell + file tools
    file operations         read/write/edit primitives (local, SSH remote, sandbox)
    parse_xml_actions       <shell> / <edit> / <write> tag extraction
    MarkdownStream          incremental markdown printing with tool-block buffering
    StreamRenderer          think-block + content state machine over streamed deltas
    LLMClient               OpenAI-compatible chat client (blocking + SSE streaming)
    SessionStore            JSONL session logging, listing, and loading
    Agent                   tool execution, context compaction, the agent loop
    Repl                    interactive prompt, slash commands, '!' shell escape
"""
from __future__ import annotations

import argparse
import ast
import atexit
import base64
import difflib
import functools
import getpass
import glob
import json
import os
import platform
import random
import re
import select
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import readline  # enables line editing/history for input(); POSIX only
except ImportError:  # pragma: no cover - e.g. Windows
    readline = None  # type: ignore[assignment]

from render_markdown import render_md, MD_BLANK, _is_md_list_item
from highlighters import highlight_bash

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

APP_NAME = "localagent"
CLI_VERSION = 5

HTTP_REQUEST_TIMEOUT = 600       # seconds, for chat completions
MODEL_INFO_TIMEOUT = 5           # seconds, for /v1/models
MODEL_INFO_RETRIES = 5

FALLBACK_N_CTX = 90_000
MAX_FILE_SIZE = 256 * 1024       # bytes, local file-read cap
MAX_OUTPUT_LINES = 1_000         # shell output lines before truncating to a temp file
MAX_TOOL_ITERATIONS = 50         # max model<->tool round trips per user turn

# Fractions of the context window used for budgeting.
COMPRESS_PCT = 0.50              # start compressing old tool output
SUMMARIZE_PCT = 0.70             # start summarizing old turns
TURN_PREFIX_PCT = 0.20           # recent-turn budget kept verbatim when summarizing
MAX_TOKENS_PCT = 0.85            # completion token cap

# ──────────────────────────────────────────────────────────────────────────────
# ANSI palette
# ──────────────────────────────────────────────────────────────────────────────

RESET, BOLD, ITALIC, STRIKE, CLEAR_LINE = "\033[0m", "\033[1m", "\033[3m", "\033[9m", "\033[K"
GRAY, CYAN, GREEN, RED, YELLOW = "\033[90m", "\033[36m", "\033[32m", "\033[31m", "\033[33m"
THINK_COLOR = "\033[3;90m"
INLINE_CODE_BG = "\033[48;5;238m"
H1_COLOR, H2_COLOR, H3_COLOR = "\033[1;4;38;5;213m", "\033[1;38;5;213m", "\033[1;38;5;177m"
CODE_BG, XML_BG = "\033[48;5;236;38;5;253m", "\033[48;5;129;38;5;255m"
QUOTE_COLOR, LIST_BULLET, TABLE_BORDER = "\033[38;5;245;3m", "\033[38;5;214m", "\033[38;5;239m"
LINK_TEXT, LINK_URL = "\033[38;5;111;4m", "\033[38;5;240m"
SHELL_OUTPUT_BG = "\033[48;5;235;90m"  # faint dark bg + dim gray text

# ──────────────────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────────────────

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

Only modify files after user approval or user instruction.
"""

SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Produce a structured summary of the conversation history.
Format exactly as follows:
## 1. Long-Term Goals
## 2. Short-Term Goals
## 3. Key Decisions & Rationale
## 4. Key Artifacts & Modifications
## 5. Previous Attempts & Failures
## 6. Current State of Ongoing Work
## 7. Next Steps
"""

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration. CLI flags take precedence over env vars."""

    yolo: bool
    sandbox: bool
    cpus: float
    memory: str
    host: str
    model: str
    temperature: float
    n_ctx_override: int | None
    task: str | None


def parse_config(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description="localagent – AI-powered terminal agent for shell execution, file editing, and writing.",
        epilog=(
            "Examples:\n"
            "  %(prog)s                Start interactive REPL\n"
            "  %(prog)s --yolo                 Start in auto-execute mode\n"
            "  %(prog)s --sandbox              Run inside a secure Docker sandbox\n"
            '  %(prog)s "fix the auth bug"     One-shot: run a task and exit\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-y", "--yolo", action="store_true",
                        help="Enable auto-execute mode (skip y/n confirmations)")
    parser.add_argument("--sandbox", action="store_true",
                        help="Launch the agent in an isolated Docker container")
    parser.add_argument("--cpus", type=float, default=2.0,
                        help="Limit CPU cores for sandbox (default: 2, e.g. 2 or 0.5)")
    parser.add_argument("--memory", type=str, default="4g",
                        help="Limit memory for sandbox (default: 4g, e.g. '4g', '512m')")
    parser.add_argument("--host", default=None,
                        help="LLM host URL (overrides LLM_HOST env var)")
    parser.add_argument("--model", default=None,
                        help="Model name (overrides LLM_MODEL env var)")
    parser.add_argument("--temperature", type=float, default=None,
                        help="Temperature for LLM responses (overrides LLM_TEMPERATURE env var)")
    parser.add_argument("--n-ctx", type=int, default=None,
                        help="Context window size (overrides LLM_N_CTX env var)")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s v{CLI_VERSION}")
    parser.add_argument("task", nargs="?", default=None, help="One-shot task: run it and exit")
    args = parser.parse_args(argv)

    return Config(
        yolo=args.yolo,
        sandbox=args.sandbox,
        cpus=args.cpus,
        memory=args.memory,
        host=args.host or os.getenv("LLM_HOST", "http://localhost:8080"),
        model=args.model or os.getenv("LLM_MODEL", "local-model"),
        temperature=(args.temperature if args.temperature is not None
                     else float(os.getenv("LLM_TEMPERATURE", "0.7"))),
        n_ctx_override=args.n_ctx,
        task=args.task,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Model discovery & context limits
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelInfo:
    n_ctx: int
    model_id: str
    quant: str


@dataclass(frozen=True)
class ContextLimits:
    window: int
    max_tokens: int
    compress_threshold: int
    summarize_threshold: int
    turn_prefix_tokens: int

    @classmethod
    def from_window(cls, n_ctx: int) -> "ContextLimits":
        return cls(
            window=n_ctx,
            max_tokens=int(n_ctx * MAX_TOKENS_PCT),
            compress_threshold=int(n_ctx * COMPRESS_PCT),
            summarize_threshold=int(n_ctx * SUMMARIZE_PCT),
            turn_prefix_tokens=int(n_ctx * TURN_PREFIX_PCT),
        )


def extract_quant(model_id: str) -> str:
    match = re.search(r"(Q\d+_[A-Z0-9_]+(?:\.\d+)?)", model_id)
    return match.group(1) if match else ""


def fetch_model_info(host: str) -> ModelInfo:
    """Query GET /v1/models, retrying on connection errors. Raises on final failure."""
    req = urllib.request.Request(
        f"{host}/v1/models", headers={"Content-Type": "application/json"}, method="GET"
    )
    data: dict[str, Any] = {}
    for attempt in range(1, MODEL_INFO_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=MODEL_INFO_TIMEOUT) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.URLError as exc:
            if attempt == MODEL_INFO_RETRIES:
                raise
            wait = float(attempt)
            print(
                f"[!] /v1/models unreachable (attempt {attempt}/{MODEL_INFO_RETRIES}): "
                f"{exc.reason}. Retrying in {wait:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)

    n_ctx, model_id, quant = FALLBACK_N_CTX, "", ""
    for model in data.get("data", []):
        meta = model.get("meta") or {}
        ctx = meta.get("n_ctx") or meta.get("n_ctx_train")
        if ctx:
            n_ctx = int(ctx)
        if model.get("id"):
            model_id = model["id"]
            quant = extract_quant(model_id)
            break
    return ModelInfo(n_ctx=n_ctx, model_id=model_id, quant=quant)


def resolve_model_and_limits(config: Config) -> tuple[ModelInfo, ContextLimits]:
    try:
        info = fetch_model_info(config.host)
    except Exception:
        info = ModelInfo(n_ctx=FALLBACK_N_CTX, model_id="", quant="")
    n_ctx = config.n_ctx_override or int(os.getenv("LLM_N_CTX", str(info.n_ctx)))
    return info, ContextLimits.from_window(n_ctx)


def model_label(info: ModelInfo, window: int) -> str:
    """Human-readable model tag for the REPL banner, e.g. 'mymodel (Q4_K_M) - 90k ctx'."""
    if not info.model_id:
        return ""
    name = info.model_id.split(":")[0]
    tag = f"{name} ({info.quant})" if info.quant else name
    return f"{tag} - {window // 1000}k ctx"


# ──────────────────────────────────────────────────────────────────────────────
# Small generic helpers
# ──────────────────────────────────────────────────────────────────────────────


def format_relative_time(ts: float) -> str:
    diff = time.time() - ts
    for unit, seconds in (("d", 86_400), ("h", 3_600), ("m", 60)):
        if diff >= seconds:
            return f"{int(diff // seconds)}{unit} ago"
    return "just now"


_SAFE_READ_BINS = frozenset(
    {"cat", "sed", "head", "tail", "wc", "grep", "find", "ls", "pwd", "echo", "date", "file", "which"}
)
_DANGEROUS_PATTERNS = (
    "| rm", "xargs rm", "| sh", "| bash", ">", "; rm", "; mv", "&& rm", "`", "$(",
)


def is_safe_read_command(cmd: str) -> bool:
    """True if `cmd` is a known read-only command with no dangerous composition."""
    cmd = cmd.strip()
    words = cmd.split()
    if not words or words[0] not in _SAFE_READ_BINS:
        return False
    if any(pattern in cmd for pattern in _DANGEROUS_PATTERNS):
        return False
    if words[0] == "sed" and "-i" in cmd:
        return False
    if words[0] == "find" and ("-exec" in cmd or "-delete" in cmd):
        return False
    return True


def check_python_syntax(path: str, content: str) -> tuple[bool, str | None]:
    """Parse .py content with ast; non-Python files always pass."""
    if not path.endswith(".py"):
        return True, None
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as exc:
        return False, str(exc)


def system_summary(cwd: str) -> dict[str, Any]:
    info: dict[str, Any] = {
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
            info["memory_total_gb"] = round(
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1
            )
        except (ValueError, OSError):
            pass
    return info


def estimate_tokens(messages: Iterable[dict[str, Any]]) -> int:
    """Crude token estimate: ~4 characters per token."""
    return sum(len(m.get("content", "")) // 4 for m in messages)


def _shell_output(cmd: str) -> str | None:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def _tmux_window_id() -> str | None:
    return _shell_output("tmux display-message -p '#{window_id}' 2>/dev/null")


def set_terminal_title(title: str) -> None:
    print(f"\033]0;{title}\007", end="", flush=True)
    window = _tmux_window_id()
    if window:
        _shell_output(f"tmux rename-window -t {window} {title!r} 2>/dev/null")


def print_shaded(line: str) -> None:
    """Print a shell-output line on a faint full-width background."""
    width = shutil.get_terminal_size((80, 20)).columns
    print(f"{SHELL_OUTPUT_BG}{line.rstrip().ljust(width)}{CLEAR_LINE}{RESET}")


def confirm(prompt: str = "(y/n): ") -> bool:
    """Prompt for a y/n confirmation. Ctrl+C / EOF counts as 'no'."""
    print(f"{BOLD}{prompt}{RESET}", end="", flush=True)
    try:
        return input().strip().lower() == "y"
    except (KeyboardInterrupt, EOFError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Docker sandbox
# ──────────────────────────────────────────────────────────────────────────────


class Sandbox:
    """A persistent, network-less Docker container.

    The agent process runs on the host; shell commands and file operations are
    executed inside the container, which bind-mounts the host CWD at /workspace.
    """

    IMAGE = "localagent-image"
    WORKDIR = "/workspace"
    _DOCKERFILE = "FROM python:3.12-alpine\nRUN apk add --no-cache git tmux\nWORKDIR /workspace\n"

    def __init__(self, cpus: float | None, memory: str | None):
        self.cpus = cpus
        self.memory = memory
        self.container = f"agent-sandbox-{os.getpid()}-{int(time.time())}"

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._ensure_image()
        cmd = [
            "docker", "run", "-d", "--name", self.container,
            "--network", "none",
            "--cap-drop=ALL", "--read-only", "--tmpfs", "/tmp:exec",
            "-u", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
            "-v", f"{os.getcwd()}:{self.WORKDIR}:rw", "-w", self.WORKDIR,
        ]
        if self.cpus is not None:
            cmd += ["--cpus", str(self.cpus)]
        if self.memory is not None:
            cmd += ["--memory", self.memory]
        cmd += [self.IMAGE, "tail", "-f", "/dev/null"]
        subprocess.run(cmd, check=True, capture_output=True)
        atexit.register(self.stop)

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)

    def _ensure_image(self) -> None:
        inspect = subprocess.run(
            ["docker", "image", "inspect", self.IMAGE], capture_output=True
        )
        if inspect.returncode == 0:
            return
        print(f"[*] Docker image '{self.IMAGE}' not found. Building it automatically...")
        try:
            subprocess.run(
                ["docker", "build", "-t", self.IMAGE, "-"],
                input=self._DOCKERFILE, text=True, check=True, capture_output=True,
            )
            print("[*] Image built successfully!\n")
        except subprocess.CalledProcessError:
            print("[!] Error: Failed to build the Docker image. Ensure Docker is running.")
            sys.exit(1)

    # -- path mapping ----------------------------------------------------------

    def host_to_container_path(self, path: str) -> str:
        """Map a model-provided path to a /workspace path inside the container."""
        expanded = Path(path).expanduser()
        if expanded.is_absolute():
            rel = os.path.relpath(str(expanded), self.WORKDIR)
            return f"{self.WORKDIR}/{rel}"
        return str(Path(self.WORKDIR) / expanded)

    # -- operations -------------------------------------------------------------

    def exec_stream(self, cmd: str) -> tuple[list[str], int]:
        """Run a command inside the container, streaming output to the terminal."""
        proc = subprocess.Popen(
            ["docker", "exec", "-i", self.container, "sh", "-c", cmd],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        lines: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line.rstrip("\n"))
                print_shaded(line)
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            lines.append("[Interrupted]")
        return lines, proc.returncode

    def read_file(self, container_path: str) -> tuple[str | None, str | None]:
        proc = subprocess.run(
            ["docker", "exec", self.container, "cat", container_path],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return None, proc.stderr.strip()
        return proc.stdout, None

    def write_file(self, container_path: str, content: str) -> bool:
        subprocess.run(
            ["docker", "exec", "-i", self.container, "sh", "-c",
             f"mkdir -p '{os.path.dirname(container_path)}'"],
            capture_output=True,
        )
        proc = subprocess.run(
            ["docker", "exec", "-i", self.container, "sh", "-c", f"cat > '{container_path}'"],
            input=content, text=True, capture_output=True,
        )
        return proc.returncode == 0


# ──────────────────────────────────────────────────────────────────────────────
# File operations (local / SSH remote / sandbox)
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_within(base_dir: str, path: str, allow_escape: bool) -> tuple[Path | None, str | None]:
    """Resolve `path` against `base_dir`; report 'path_escapes' if it leaves it."""
    base = Path(base_dir).resolve()
    target = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
    if not allow_escape and not target.is_relative_to(base):
        return None, "path_escapes"
    return target, None


def read_file(
    path: str,
    base_dir: str,
    *,
    remote: str | None = None,
    sandbox: Sandbox | None = None,
    allow_escape: bool = False,
) -> tuple[str | None, str | None]:
    """Read a file. Returns (content, error); exactly one is None.

    Empty files read as the sentinel string "[empty]".
    """
    if remote:
        proc = subprocess.run(
            f"ssh {remote} \"cat '{path}'\"", shell=True, capture_output=True, text=True
        )
        if proc.returncode != 0:
            return None, proc.stderr.strip()
        return proc.stdout, None

    if sandbox is not None:
        try:
            _, err = _resolve_within(base_dir, path, allow_escape)
            if err:
                return None, err
        except Exception:
            pass  # boundary check is best-effort; the container is the real boundary
        content, err = sandbox.read_file(sandbox.host_to_container_path(path))
        if err is not None:
            return None, "not found"
        return (content or "[empty]"), None

    try:
        raw = Path(base_dir, Path(path).expanduser())
        target, err = _resolve_within(base_dir, path, allow_escape)
        if err:
            return None, err
        assert target is not None
        if not target.exists():
            return None, "not found"
        if raw.is_symlink():
            base = Path(base_dir).resolve()
            if not allow_escape and not raw.resolve().is_relative_to(base):
                return None, "symlink escapes repo boundary"
        if not stat.S_ISREG(target.stat().st_mode):
            return None, "not a regular file"
        if target.stat().st_size > MAX_FILE_SIZE:
            return None, "file too large"
        content = target.read_text(encoding="utf-8")
        return (content or "[empty]"), None
    except UnicodeDecodeError:
        return None, "binary/not UTF-8"
    except Exception as exc:
        return None, str(exc)


def write_file(
    path: str,
    content: str,
    base_dir: str,
    *,
    remote: str | None = None,
    sandbox: Sandbox | None = None,
    allow_escape: bool = False,
) -> str | None:
    """Write a file. Returns an error string, or None on success."""
    if remote:
        tmp = f"{path}.tmp.{random.randint(100_000, 999_999)}"
        proc = subprocess.run(
            f"ssh {remote} \"cat > '{tmp}' && mv '{tmp}' '{path}'\"",
            shell=True, input=content, text=True, capture_output=True,
        )
        return proc.stderr.strip() if proc.returncode != 0 else None

    if sandbox is not None:
        try:
            _, err = _resolve_within(base_dir, path, allow_escape)
            if err:
                return err
        except Exception:
            pass
        ok = sandbox.write_file(sandbox.host_to_container_path(path), content)
        return None if ok else "write failed"

    try:
        target, err = _resolve_within(base_dir, path, allow_escape)
        if err:
            return err
        assert target is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return None
    except Exception as exc:
        return str(exc)


# ──────────────────────────────────────────────────────────────────────────────
# Text normalization, find/replace, diffing, highlighting
# ──────────────────────────────────────────────────────────────────────────────

_UNICODE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\u2018\u2019\u201a\u201b]"), "'"),    # curly single quotes
    (re.compile(r"[\u201c\u201d\u201e\u201f]"), '"'),    # curly double quotes
    (re.compile(r"[\u2010-\u2015\u2212]"), "-"),         # dashes / minus
    (re.compile(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]"), " "),  # exotic spaces
)


def normalize_text(text: str, strict: bool = False) -> str:
    """Normalize line endings; unless strict, also NFKC-fold and ASCII-ify punctuation."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict:
        return text
    text = "\n".join(line.rstrip() for line in unicodedata.normalize("NFKC", text).split("\n"))
    for pattern, replacement in _UNICODE_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def find_and_replace(
    content: str, old_text: str, new_text: str, path: str, strict: bool = False
) -> tuple[str, str, int, int]:
    """Locate `old_text` in `content` (exact, then fuzzy unless strict) and replace it.

    Returns (base_content, new_content, start_line, end_line), lines 1-based.
    Raises ValueError on no match or ambiguous matches.
    """
    if not old_text:
        raise ValueError("oldText empty")

    idx = content.find(old_text)
    if idx != -1:
        if content.count(old_text) > 1:
            raise ValueError("Multiple exact matches found.")
        start_line = content[:idx].count("\n") + 1
        end_line = content[idx:idx + len(old_text)].count("\n") + start_line
        return content, content[:idx] + new_text + content[idx + len(old_text):], start_line, end_line

    if strict:
        raise ValueError(
            f"Text not found in {path}. Provide an exact match (including whitespace/indentation)."
        )

    base, norm_old = normalize_text(content), normalize_text(old_text)
    idx = base.find(norm_old)
    if idx == -1:
        raise ValueError(f"Text not found in {path}. Check whitespace/indentation.")
    if base.count(norm_old) > 1:
        raise ValueError("Multiple fuzzy matches found.")
    start_line = base[:idx].count("\n") + 1
    end_line = base[idx:idx + len(norm_old)].count("\n") + start_line
    return base, base[:idx] + new_text + base[idx + len(norm_old):], start_line, end_line


def format_diff(old: str, new: str, context: int = 1) -> str:
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), n=context, lineterm="")
    return "\n".join(
        f" {RESET} ..." if line.startswith("@@") else line
        for line in diff
        if not line.startswith(("---", "+++"))
    )


_EXTENSION_LANGS = {
    ".py": "python", ".pyi": "python",
    ".sh": "bash", ".bash": "bash",
    ".html": "html", ".htm": "html",
}


def _highlighter_for(path: str):
    """Return a highlight function for the file's language, or None."""
    lang = _EXTENSION_LANGS.get(os.path.splitext(path)[1].lower())
    if not lang:
        return None
    try:
        from highlighters import get_highlighter
        highlight_fn, _ = get_highlighter(lang)
        return highlight_fn
    except (KeyError, ImportError):
        return None


def print_highlighted_content(content: str, path: str, prefix: str = "+", max_lines: int = 10) -> None:
    """Print file content with syntax highlighting if available, else plain green."""
    highlight_fn = _highlighter_for(path)
    lines = content.splitlines()
    display = highlight_fn(content).splitlines() if highlight_fn else lines

    for i, line in enumerate(display):
        if max_lines and i >= max_lines:
            break
        if highlight_fn:
            print(f"{GREEN}{prefix}{RESET}{line}{RESET}")
        else:
            print(f"{GREEN}{prefix}{line}{RESET}")

    if max_lines and len(lines) > max_lines:
        print(f"{GRAY}... ({len(lines) - max_lines} more lines){RESET}")


# ──────────────────────────────────────────────────────────────────────────────
# XML action parsing
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Action:
    type: str                 # "shell" | "edit" | "write"
    remote: str | None
    path: str
    command: str = ""         # shell
    content: str = ""         # write
    find: str = ""            # edit
    replace: str = ""         # edit


# Branch 1: <shell> may appear inline or multiline anywhere.
# Branch 2: <edit>/<write> strictly require open/close tags at the start of a line.
_ACTION_RE = re.compile(
    r"(?m)"
    r"<(shell)\b([^>]*)>([\s\S]*?)</\1>|"
    r'^[ \t]*<(edit|write)\b(?=[^>]*\bpath="[^"]+")([^>]*)>\n([\s\S]*?)\n^[ \t]*</\4>'
)
_PATH_ATTR_RE = re.compile(r'\bpath="([^"]+)"')
_REMOTE_ATTR_RE = re.compile(r'\bremote="([^"]+)"')
# <find>/<replace> are anchored to line starts to avoid nested-tag collisions.
_FIND_RE = re.compile(r"(?m)^[ \t]*<find>\n([\s\S]*?)\n^[ \t]*</find>")
_REPLACE_RE = re.compile(r"(?m)^[ \t]*<replace>\n([\s\S]*?)\n^[ \t]*</replace>")


def parse_xml_actions(text: str) -> list[Action]:
    actions: list[Action] = []
    for match in _ACTION_RE.finditer(text):
        if match.group(1):
            tag, attrs, inner = match.group(1), match.group(2), match.group(3)
        else:
            tag, attrs, inner = match.group(4), match.group(5), match.group(6)

        path_m = _PATH_ATTR_RE.search(attrs)
        remote_m = _REMOTE_ATTR_RE.search(attrs)
        path = path_m.group(1) if path_m else ""
        remote = remote_m.group(1) if remote_m else None

        if tag == "shell":
            actions.append(Action(type="shell", remote=remote, path=path, command=inner.strip()))
        elif tag == "write":
            actions.append(Action(type="write", remote=remote, path=path, content=inner.strip()))
        else:  # edit
            find_m = _FIND_RE.search(inner)
            replace_m = _REPLACE_RE.search(inner)
            actions.append(Action(
                type="edit", remote=remote, path=path,
                find=find_m.group(1).strip("\n") if find_m else "",
                replace=replace_m.group(1).strip("\n") if replace_m else "",
            ))
    return actions


# ──────────────────────────────────────────────────────────────────────────────
# Spinner
# ──────────────────────────────────────────────────────────────────────────────


class Spinner:
    """A minimal terminal spinner shown while waiting on the LLM."""

    _FRAMES = "|/-\\"

    def __init__(self):
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = self._FRAMES[i % len(self._FRAMES)]
            print(f"\r{GRAY}{frame} {RESET}", end="", flush=True)
            i += 1
            time.sleep(0.1)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        print(f"\r{CLEAR_LINE}", end="", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Streaming output rendering
# ──────────────────────────────────────────────────────────────────────────────


class MarkdownStream:
    """Incrementally prints streamed markdown.

    Complete lines are rendered as they arrive. Tool blocks (<shell>/<edit>/<write>)
    are buffered until their closing tag appears, then rendered atomically. Blank
    lines and header/list transitions get the same spacing a batch renderer would
    produce.
    """

    _TOOL_TAGS = ("write", "edit", "shell")

    def __init__(self):
        self._buf = ""
        self._prev = "other"  # one of: "header", "list", "blank", "other"

    def feed(self, text: str) -> None:
        self._buf += text
        self._flush()

    def _flush(self) -> None:
        while self._buf:
            stripped = self._buf.lstrip(" \t\r\n")
            if not stripped:
                return

            verdict = self._try_tool_block(stripped)
            if verdict == "incomplete":
                return          # wait for more chunks
            if verdict == "emitted":
                continue        # a tool block was printed; keep scanning

            newline = self._buf.find("\n")
            if newline == -1:
                return          # no complete line yet
            line, self._buf = self._buf[:newline], self._buf[newline + 1:]
            self._emit_line(line)

    def _try_tool_block(self, stripped: str) -> str:
        """Returns 'emitted', 'incomplete', or 'none'."""
        for tag in self._TOOL_TAGS:
            open_sig, close_sig = f"<{tag}", f"</{tag}>"
            if stripped.startswith(open_sig):
                end = self._buf.find(close_sig)
                if end == -1:
                    return "incomplete"
                block_end = end + len(close_sig)
                block, self._buf = self._buf[:block_end], self._buf[block_end:]
                rendered = render_md(block)
                if rendered:
                    print(rendered)
                self._prev = "other"
                return "emitted"
            if open_sig.startswith(stripped):  # buffer is a prefix of an opening tag
                return "incomplete"
        return "none"

    def _emit_line(self, line: str) -> None:
        rendered = render_md(line)
        if rendered is MD_BLANK:
            self._prev = "blank"
            return
        if not rendered:
            return

        is_header = line.startswith(("# ", "## ", "### "))
        is_list = (not is_header) and _is_md_list_item(line.lstrip())

        if is_header:
            print()
        elif self._prev in ("header", "blank") and not is_list:
            print()
        elif self._prev == "list" and not is_list:
            print()
        print(rendered)

        self._prev = "header" if is_header else "list" if is_list else "other"

    def finish(self) -> None:
        """Render whatever remains in the buffer (possibly an unterminated block)."""
        if not self._buf.strip():
            return
        self._flush()
        remaining = self._buf.strip()
        self._buf = ""
        if not remaining:
            return
        rendered = render_md(remaining)
        if rendered is MD_BLANK or not rendered:
            return
        is_header = remaining.startswith(("# ", "## ", "### "))
        if is_header or self._prev in ("header", "list", "blank"):
            print()
        print(rendered)


class StreamRenderer:
    """State machine over streamed deltas: dims 'think' segments, renders the rest.

    Two thinking styles are supported:
      * native — the API sends `reasoning_content` deltas
      * inline — the model emits literal <think>...</think> inside `content`
    Partial tags spanning chunk boundaries are held back until resolvable.
    The full transcript (with <think> markers) is preserved for the message log.
    """

    def __init__(self):
        self._md = MarkdownStream()
        self._raw = ""               # undecided content (possible partial think tags)
        self._transcript: list[str] = []
        self._native_think = False
        self._inline_think = False

    def on_reasoning(self, text: str) -> None:
        if not text:
            return
        if not self._native_think:
            print("\n" + THINK_COLOR + "> ", end="", flush=True)
            self._native_think = True
            self._transcript.append("<think>\n")
        print(text, end="", flush=True)
        self._transcript.append(text)

    def on_content(self, text: str) -> None:
        if not text:
            return
        if self._native_think:
            print(RESET + "\n", end="", flush=True)
            self._native_think = False
            self._transcript.append("\n</think>\n")
        self._transcript.append(text)
        self._raw += text
        self._drain()

    def _drain(self) -> None:
        while self._raw:
            if self._inline_think:
                if "</think>" in self._raw:
                    before, _, after = self._raw.partition("</think>")
                    print(before, end="", flush=True)
                    print(RESET + "\n", end="", flush=True)
                    self._inline_think = False
                    self._raw = after
                    continue
                held_at = self._partial_tag_index("/think")
                if held_at is not None:
                    print(self._raw[:held_at], end="", flush=True)
                    self._raw = self._raw[held_at:]
                    return
                print(self._raw, end="", flush=True)
                self._raw = ""
            else:
                if "<think>" in self._raw:
                    before, _, after = self._raw.partition("<think>")
                    if before:
                        self._md.feed(before)
                    print("\n" + THINK_COLOR + "> ", end="", flush=True)
                    self._inline_think = True
                    self._raw = after
                    continue
                held_at = self._partial_tag_index("think")
                if held_at is not None:
                    self._md.feed(self._raw[:held_at])
                    self._raw = self._raw[held_at:]
                    return
                self._md.feed(self._raw)
                self._raw = ""

    def _partial_tag_index(self, tag_name: str) -> int | None:
        """Index of a trailing '<' that could begin `<tag_name>`, else None."""
        idx = self._raw.rfind("<")
        if idx != -1 and not self._raw.endswith(">") and tag_name.startswith(self._raw[idx + 1:]):
            return idx
        return None

    def finish(self) -> str:
        """Close open styling, flush remaining markdown, return the full transcript."""
        if self._native_think or self._inline_think:
            print(RESET, end="", flush=True)
        self._md.finish()
        print()
        return "".join(self._transcript)


# ──────────────────────────────────────────────────────────────────────────────
# LLM client
# ──────────────────────────────────────────────────────────────────────────────


class LLMClient:
    """Minimal OpenAI-compatible chat-completions client (stdlib only)."""

    def __init__(self, host: str, model: str, temperature: float, limits: ContextLimits):
        self.host = host  # mutable: the /host REPL command changes it at runtime
        self.model = model
        self.temperature = temperature
        self.limits = limits

    def _payload(self, messages: list[dict[str, Any]], stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.limits.max_tokens,
            "cache_prompt": True,
        }
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _open(self, payload: dict[str, Any]):
        req = urllib.request.Request(
            f"{self.host}/v1/chat/completions",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode(),
        )
        return urllib.request.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT)

    def complete(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Blocking completion. Returns the raw API response dict, or None on error."""
        spinner = Spinner()
        spinner.start()
        try:
            with self._open(self._payload(messages, stream=False)) as resp:
                spinner.stop()
                return json.loads(resp.read().decode())
        except KeyboardInterrupt:
            spinner.stop()
            raise
        except Exception as exc:
            spinner.stop()
            print(f"{RED}[API Error: {exc}]{RESET}")
            return None

    def stream(self, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Streaming completion, rendered live to the terminal.

        Returns {"content": str, "usage": dict, "timings": dict}, or None on error.
        """
        spinner = Spinner()
        spinner.start()
        try:
            with self._open(self._payload(messages, stream=True)) as resp:
                spinner.stop()
                return self._consume_sse(resp)
        except KeyboardInterrupt:
            spinner.stop()
            raise
        except Exception as exc:
            spinner.stop()
            print(f"{RED}[API Error: {exc}]{RESET}")
            return None

    @staticmethod
    def _consume_sse(resp) -> dict[str, Any]:
        renderer = StreamRenderer()
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}

        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line or line.startswith(":"):
                continue
            if line == "data: [DONE]":
                break
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = chunk["usage"]
            if chunk.get("timings"):
                timings = chunk["timings"]

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            renderer.on_reasoning(delta.get("reasoning_content") or "")
            renderer.on_content(delta.get("content") or "")

        return {"content": renderer.finish(), "usage": usage, "timings": timings}


# ──────────────────────────────────────────────────────────────────────────────
# Session logging
# ──────────────────────────────────────────────────────────────────────────────


class SessionStore:
    """Append-only JSONL session logs under ~/.localagent/logs/<project>/."""

    def __init__(self, cwd: str):
        self.dir = Path.home() / ".localagent" / "logs" / Path(cwd).name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.dir / f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self.append({"type": "session", "cwd": cwd, "started_at": time.time()})

    def append(self, record: dict[str, Any]) -> None:
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log_message(self, role: str, content: str) -> None:
        self.append({"type": "message", "ts": time.time(), "role": role, "content": content})

    def log_tool(self, tool: str, success: bool, **meta: Any) -> None:
        self.append({"type": "tool", "ts": time.time(), "tool": tool, "success": success, **meta})

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.dir.glob("*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            if not lines:
                continue
            mtime = path.stat().st_mtime
            meta: dict[str, Any] = {
                "id": path.stem, "started_at": mtime, "last_message_at": mtime,
                "messages": 0, "last_user_message": None,
            }
            try:
                first = json.loads(lines[0])
                if first.get("type") == "session":
                    meta["started_at"] = first.get("started_at", mtime)
            except json.JSONDecodeError:
                pass
            # Cheap substring pre-filter avoids parsing every line of large logs.
            for line in lines:
                if '"type": "message"' not in line:
                    continue
                meta["messages"] += 1
                if '"role": "user"' in line:
                    try:
                        meta["last_user_message"] = json.loads(line)
                    except json.JSONDecodeError:
                        pass
            sessions.append(meta)
        return sessions

    def load_messages(self, session_id: str) -> list[dict[str, str]]:
        """Load a session's non-system messages as clean {role, content} dicts."""
        messages: list[dict[str, str]] = []
        with open(self.dir / f"{session_id}.jsonl", encoding="utf-8") as f:
            for line in f:
                if '"type": "message"' not in line:
                    continue
                record = json.loads(line)
                if record.get("role") == "system":
                    continue
                messages.append({"role": record["role"], "content": record.get("content", "")})
        return messages


# ──────────────────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────────────────


class Agent:
    """Owns the conversation, executes tool actions, and manages context size."""

    _SUDO_RE = re.compile(r"(^|\s|;|&&|\|\|)sudo\b")

    def __init__(self, config: Config, client: LLMClient, sandbox: Sandbox | None = None):
        self.config = config
        self.client = client
        self.sandbox = sandbox
        self.auto_mode = config.yolo
        self.cwd = Sandbox.WORKDIR if sandbox else os.getcwd()
        self.store = SessionStore(self.cwd)

        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()}
        ]
        self.pending_notes: list[str] = []
        self._compaction_summary = ""
        self._initial_context_sent = False
        # base64 is obfuscation only — avoids plaintext passwords in heap dumps/tracebacks.
        self._sudo_passwords: dict[str, str] = {}

    # -- setup -------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt() -> str:
        prompt = XML_SYSTEM_PROMPT
        for candidate in (Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"):
            if candidate.exists():
                prompt += f"\n\n### AGENTS.md\n{candidate.read_text('utf-8').strip()}"
                break
        return prompt

    # -- sudo --------------------------------------------------------------------

    def _get_sudo_password(self, remote: str) -> str | None:
        encoded = self._sudo_passwords.get(remote)
        if encoded:
            return base64.b64decode(encoded).decode()
        print(f"{YELLOW}[sudo] password for {remote}:{RESET}", end=" ", flush=True)
        try:
            password = getpass.getpass()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not password:
            print(f"{RED}[No password provided. sudo commands will fail.]{RESET}")
            return None
        self._sudo_passwords[remote] = base64.b64encode(password.encode()).decode()
        return password

    def _wrap_sudo(self, cmd: str, remote: str) -> str:
        if not self._SUDO_RE.search(cmd):
            return cmd
        password = self._get_sudo_password(remote)
        if password is None:
            return cmd
        escaped = password.replace("'", "'\\''")
        return f"echo '{escaped}' | sudo -S {cmd}"

    # -- command execution ---------------------------------------------------------

    def stream_command(self, cmd: str, raw: bool = False) -> tuple[list[str], int]:
        """Run a shell command (locally or in the sandbox), streaming output live."""
        if self.sandbox is not None:
            return self.sandbox.exec_stream(cmd)

        proc = subprocess.Popen(
            cmd, shell=True, executable="/bin/bash",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=self.cwd,
        )
        lines: list[str] = []
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                lines.append(line.rstrip("\n"))
                if raw:
                    print(line, end="")
                else:
                    print_shaded(line)
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            lines.append("[Interrupted]")
        return lines, proc.returncode

    # -- tool: shell ----------------------------------------------------------------

    def _execute_shell(self, action: Action) -> str:
        cmd, remote = action.command, action.remote
        is_safe = is_safe_read_command(cmd) and not remote
        prompt_color = GRAY if is_safe else CYAN
        remote_prefix = f"[{remote}] " if remote else ""
        print(f"{prompt_color}$ {remote_prefix}{RESET}{highlight_bash(cmd)}")

        if not is_safe and not self.auto_mode and not confirm():
            self.store.log_tool("shell", False, denied=True)
            return "Denied."

        if remote:
            runnable = self._wrap_sudo(cmd, remote)
            escaped = runnable.replace("\\", "\\\\").replace('"', '\\"')
            shell_cmd = f'ssh -o ConnectTimeout=10 {remote} "{escaped}"'
        else:
            shell_cmd = cmd

        lines, returncode = self.stream_command(shell_cmd)
        output = "\n".join(lines)

        if len(lines) > MAX_OUTPUT_LINES:
            fd, tmp_path = tempfile.mkstemp(prefix="localagent_sh_", suffix=".txt", text=True)
            os.close(fd)
            Path(tmp_path).write_text(output, encoding="utf-8")
            output = f"...\n[Output truncated. Full saved to {tmp_path}]\n..."

        self.store.log_tool("shell", returncode == 0, cmd=cmd)
        return f"Command: {cmd}\nExit Code: {returncode}\nOutput:\n{output}"

    # -- tool: edit -------------------------------------------------------------------

    def _path_escapes(self, path: str) -> bool:
        if self.sandbox is not None:
            return False  # the container is the boundary
        try:
            resolved = Path(self.cwd, Path(path).expanduser()).resolve()
            return not resolved.is_relative_to(Path(self.cwd).resolve())
        except Exception:
            return False

    def _execute_edit(self, action: Action) -> str:
        path, remote = action.path, action.remote

        content, err = read_file(path, self.cwd, remote=remote, sandbox=self.sandbox)
        escapes = err == "path_escapes"
        if escapes:
            resolved = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"{YELLOW}⚠ [Edit] Path escapes repo boundary: {resolved}{RESET}")
            content, err = read_file(
                path, self.cwd, remote=remote, sandbox=self.sandbox, allow_escape=True
            )
        if err:
            self.store.log_tool("edit", False, err=err)
            return f"Error reading {path}: {err}"
        assert content is not None

        try:
            base_text = normalize_text("" if content == "[empty]" else content, strict=True)
            base, new, start_line, end_line = find_and_replace(
                base_text, action.find, action.replace, path, strict=bool(remote)
            )
        except Exception as exc:
            self.store.log_tool("edit", False, err=str(exc))
            return f"Edit failed: {exc}"

        ok, syntax_err = check_python_syntax(path, new)
        if not ok:
            self.store.log_tool("edit", False, err=syntax_err)
            return f"Syntax Error: {syntax_err}"

        diff = format_diff(base, new)
        removed = sum(1 for line in diff.splitlines() if line.startswith("-"))
        added = sum(1 for line in diff.splitlines() if line.startswith("+"))

        if escapes:
            print(f"{CYAN}Proposed changes:{RESET}")
            for line in diff.splitlines():
                color = GREEN if line.startswith("+") else RED if line.startswith("-") else GRAY
                print(f"{color}{line}{RESET}")
            if not self.auto_mode and not confirm("(Approve? y/n): "):
                self.store.log_tool("edit", False, denied=True, path=path)
                return "Denied by user."

        if write_err := write_file(
            path, new, self.cwd, remote=remote, sandbox=self.sandbox, allow_escape=escapes
        ):
            self.store.log_tool("edit", False, err=write_err)
            return f"Write failed: {write_err}"

        summary = (
            f"{remote or 'local'} -> {path}: lines {start_line}-{end_line} | "
            f"replaced {removed} lines with {added} lines"
        )
        print(f"{CYAN}[Edit] {summary}{RESET}")
        self.store.log_tool("edit", True, path=path)
        return (
            f"Successfully edited {path}: lines {start_line}-{end_line} | "
            f"replaced {removed} lines with {added} lines"
        )

    # -- tool: write -------------------------------------------------------------------

    def _execute_write(self, action: Action) -> str:
        path, remote, content = action.path, action.remote, action.content
        if not path:
            return "Error: missing 'path'."

        ok, syntax_err = check_python_syntax(path, content)
        if not ok:
            self.store.log_tool("write", False, err=syntax_err, path=path)
            return f"Syntax Error: {syntax_err}"

        n_lines = len(content.splitlines())
        escapes = self._path_escapes(path)

        if escapes:
            resolved = Path(self.cwd, Path(path).expanduser()).resolve()
            print(f"{YELLOW}⚠ [Write] Path escapes repo boundary: {resolved}{RESET}")
            print(f"{CYAN}Proposed file content ({n_lines} lines):{RESET}")
            print_highlighted_content(content, path, prefix="+", max_lines=10)
            if not self.auto_mode and not confirm("(Approve? y/n): "):
                self.store.log_tool("write", False, denied=True, path=path)
                return "Denied by user."

        if write_err := write_file(
            path, content, self.cwd, remote=remote, sandbox=self.sandbox, allow_escape=escapes
        ):
            self.store.log_tool("write", False, err=write_err)
            return f"Write failed: {write_err}"

        print(f"{CYAN}[Write] Wrote {n_lines} lines to {path}{RESET}")
        self.store.log_tool("write", True, path=path)
        return f"Wrote content to {path}"

    def _execute(self, action: Action) -> str:
        if action.type == "shell":
            return self._execute_shell(action)
        if action.type == "edit":
            return self._execute_edit(action)
        return self._execute_write(action)

    # -- context management -----------------------------------------------------------

    def _compress_context(self) -> None:
        limits = self.client.limits

        # Stage 1: squash old tool output down to head+tail excerpts.
        if estimate_tokens(self.messages) > limits.compress_threshold:
            for message in self.messages:
                content = message.get("content", "")
                if (message["role"] == "user"
                        and "### Action Results" in content
                        and len(content) > 1000):
                    message["content"] = (
                        f"{content[:500]}\n...[Compressed]...\n{content[-500:]}"
                    )

        # Stage 2: summarize everything but the most recent turns.
        if estimate_tokens(self.messages) <= limits.summarize_threshold:
            return

        accumulated, split_idx = 0, 1
        for i in range(len(self.messages) - 1, -1, -1):
            accumulated += len(self.messages[i].get("content", "")) // 4
            if accumulated > limits.turn_prefix_tokens:
                split_idx = max(1, i)
                break
        if split_idx >= len(self.messages) - 1:
            return

        prompt = "Summarize:\n" + "\n".join(
            f"[{m['role']}]\n{m['content']}" for m in self.messages[1:split_idx]
        )
        if self._compaction_summary:
            prompt = f"Prev summary:\n{self._compaction_summary}\n\nNew:\n{prompt}"

        response = self.client.complete([
            {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        if not response:
            return
        self._compaction_summary = (
            response.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        self.messages = (
            [self.messages[0],
             {"role": "assistant", "content": f"Memory Summary:\n{self._compaction_summary}"}]
            + self.messages[split_idx:]
        )

    # -- the agent loop ----------------------------------------------------------------

    def _print_turn_stats(self, usage: dict[str, Any], timings: dict[str, Any]) -> None:
        window = self.client.limits.window
        ctx_pct = usage.get("prompt_tokens", 0) / window * 100
        if timings:
            cache_pct = timings.get("cache_n", 0) / max(usage.get("prompt_tokens", 1), 1) * 100
            speed = timings.get("predicted_per_second", 0)
            print(f"{GRAY}ctx: {ctx_pct:.1f}% | cache: {cache_pct:.0f}% | {speed:.1f} t/s{RESET}")
        else:
            print(f"{GRAY}ctx: {ctx_pct:.1f}%{RESET}")

    def run_turn(self, request: str) -> None:
        if not self._initial_context_sent:
            request = f"### System\n{json.dumps(system_summary(self.cwd))}\n\n{request}"
            self._initial_context_sent = True
        if self.pending_notes:
            request = (
                "### Extra Context\n" + "\n\n".join(self.pending_notes)
                + f"\n\n### Request\n{request}"
            )
            self.pending_notes.clear()

        self.messages.append({"role": "user", "content": request})
        self.store.log_message("user", request)

        for _ in range(MAX_TOOL_ITERATIONS):
            try:
                response = self.client.stream(self.messages)
                if not response:
                    break

                text = response.get("content", "")
                self.messages.append({"role": "assistant", "content": text})
                self.store.log_message("assistant", text)

                usage = response.get("usage") or {}
                timings = response.get("timings") or {}
                if usage:
                    self._print_turn_stats(usage, timings)

                visible_text = re.sub(r"<think>[\s\S]*?</think>", "", text)
                actions = parse_xml_actions(visible_text)
                if not actions:
                    break

                print()
                results = [self._execute(action) for action in actions]
                self.messages.append({
                    "role": "user",
                    "content": "### Action Results\n\n" + "\n\n---\n\n".join(results),
                })
                self._compress_context()
            except KeyboardInterrupt:
                print(f"\n{YELLOW}⚠ Turn interrupted (Ctrl+C). Session preserved. "
                      f"Type a new request or /exit.{RESET}")
                self.messages.pop()
                self.store.append({"type": "event", "ts": time.time(), "event": "turn_interrupted"})
                break

# ──────────────────────────────────────────────────────────────────────────────
# Interactive input: readline setup, paste handling, $EDITOR composition
# ──────────────────────────────────────────────────────────────────────────────

HISTORY_FILE = Path.home() / ".localagent" / "history"
HISTORY_LENGTH = 1000
PASTE_DRAIN_TIMEOUT = 0.05  # seconds; how long a paste may pause between lines

_SLASH_COMMANDS = (
    "/auto", "/clear", "/edit", "/exit", "/help", "/host", "/load", "/quit", "/sessions",
)


class ReplCompleter:
    """Tab completion for slash commands and file paths after '@'.

    Deliberately completes nothing when the cursor sits in blank/whitespace
    context, so tabs inside pasted text do not pop a completion menu.
    """

    def __init__(self):
        self._matches: list[str] = []

    def __call__(self, text: str, state: int) -> str | None:
        if state == 0:
            self._matches = self._compute(text)
        return self._matches[state] if state < len(self._matches) else None

    @staticmethod
    def _compute(text: str) -> list[str]:
        before_word = readline.get_line_buffer()[: readline.get_begidx()]
        if not text and not before_word.strip():
            return []  # pasted tab / leading indentation: stay quiet
        if text.startswith("/") and not before_word.strip():
            return [c + " " for c in _SLASH_COMMANDS if c.startswith(text)]
        if text.startswith("@"):
            pattern = os.path.expanduser(text[1:]) + "*"
            matches: list[str] = []
            for path in sorted(glob.glob(pattern))[:50]:
                matches.append("@" + path + ("/" if os.path.isdir(path) else " "))
            return matches
        return []


def setup_readline() -> None:
    """Enable line editing, persistent history, and tab completion."""
    if readline is None:
        return
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        readline.read_history_file(HISTORY_FILE)
    except OSError:
        pass
    readline.set_history_length(HISTORY_LENGTH)
    atexit.register(_save_history)

    # Whitespace-only delimiters so '/load' and '@src/auth.py' complete as
    # whole words (the defaults treat '@' and '/' as word breaks).
    readline.set_completer_delims(" \t\n")
    readline.set_completer(ReplCompleter())
    if "libedit" in (getattr(readline, "__doc__", "") or ""):
        readline.parse_and_bind("bind ^I rl_complete")  # macOS libedit dialect
    else:
        readline.parse_and_bind("tab: complete")


def _save_history() -> None:
    try:
        readline.write_history_file(HISTORY_FILE)
    except OSError:
        pass


def drain_pending_stdin() -> list[str]:
    """Read lines already sitting in the tty buffer (i.e. the rest of a paste).

    Bypasses readline on purpose: continuation lines must not enter history or
    trigger completion. Returns immediately once the buffer goes quiet.
    """
    lines: list[str] = []
    if os.name != "posix":
        return lines  # select() on stdin is POSIX-only; degrade to single-line
    while True:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], PASTE_DRAIN_TIMEOUT)
        except (OSError, ValueError):
            break
        if not ready:
            break
        line = sys.stdin.readline()
        if not line:  # EOF
            break
        lines.append(line.rstrip("\n"))
    return lines


def editor_input() -> str | None:
    """Compose a message in $VISUAL/$EDITOR (the `git commit` pattern)."""
    fd, path = tempfile.mkstemp(prefix="localagent_", suffix=".md")
    os.close(fd)
    try:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR", "vi")
        try:
            subprocess.run([*shlex.split(editor), path])
        except (OSError, ValueError) as exc:
            print(f"{RED}Could not launch editor {editor!r}: {exc}{RESET}")
            return None
        return Path(path).read_text(encoding="utf-8").strip()
    finally:
        os.unlink(path)

# ──────────────────────────────────────────────────────────────────────────────
# REPL
# ──────────────────────────────────────────────────────────────────────────────


class Repl:
    """Interactive prompt: free-form requests, '!' shell escape, and slash commands."""

    HELP_TEXT = (
        f"{H2_COLOR}Available Commands:{RESET}\n"
        f"  {BOLD}!cmd{RESET}       Run `cmd` locally and optionally add output to context\n"
        f"  {BOLD}/sessions{RESET} List recent conversation sessions\n"
        f"  {BOLD}/load <id>{RESET} Load a previous session by its number or ID\n"
        f"  {BOLD}/edit{RESET}      Compose a request in $EDITOR (best for long/pasted text)\n"
        f"  {BOLD}/clear{RESET}     Clear conversation history (keeps system prompt)\n"
        f"  {BOLD}/auto{RESET}      Toggle auto-execute mode\n"
        f"  {BOLD}/host URL{RESET}  Change LLM host\n"
        f"  {BOLD}/exit{RESET}      Quit the agent"
    )

    def __init__(self, agent: Agent, model_tag: str):
        self.agent = agent
        self.model_tag = model_tag

    # -- input -------------------------------------------------------------------

    @staticmethod
    def _read_block() -> str | None:
        """Read one input block.

        Typed input submits on Enter. A multi-line paste is captured whole:
        readline handles the first line (editing + history), then any lines
        already pending in the tty buffer are drained without prompting.
        Returns None to quit the REPL, "" to re-prompt.
        """
        try:
            lines = [input()]
        except EOFError:
            return None
        except KeyboardInterrupt:
            print("\n[Interrupted]")
            return ""
        try:
            lines.extend(drain_pending_stdin())
        except KeyboardInterrupt:
            pass
        return "\n".join(lines).strip()

    # -- banner -------------------------------------------------------------------

    def _print_banner(self) -> None:
        host = re.sub(r"^https?://", "", self.agent.client.host)
        parts = [f"\033[1;36m⚡ {APP_NAME}{RESET}", f"{GRAY}{host}{RESET}"]
        if self.agent.sandbox is not None:
            parts.append(f"{YELLOW}[{self.agent.sandbox.container}]{RESET}")
        if self.model_tag:
            parts.append(f"{GRAY}│{RESET} \033[37m{self.model_tag}{RESET}")
        if self.agent.auto_mode:
            parts.append(f"\033[1;31m[yolo]{RESET}")
        print(" ".join(parts) + f"  {GRAY}(/help){RESET}")

    # -- '!' shell escape ------------------------------------------------------------

    def _handle_bang(self, raw: str) -> None:
        cmd = raw[1:].strip()
        lines, _ = self.agent.stream_command(cmd, raw=True)
        try:
            if input("\n\aAdd to context? [y/N]: ").strip().lower() == "y":
                self.agent.pending_notes.append(f"$ {cmd}\n" + "\n".join(lines[-100:]))
                print(f"{GREEN}Added to context.{RESET}")
        except KeyboardInterrupt:
            pass

    # -- slash commands -----------------------------------------------------------------

    @staticmethod
    def _session_preview(session: dict[str, Any]) -> str:
        message = session.get("last_user_message")
        if not message:
            return ""
        content = message.get("content", "")
        match = re.search(r"### Request\n(.+)", content, re.S)
        text = match.group(1) if match else content[:60]
        return text.replace("\n", " ")[:47] + "..."

    def _cmd_sessions(self) -> None:
        print(f"{CYAN}Recent conversations:{RESET}")
        for i, session in enumerate(self.agent.store.list_sessions()[:10], 1):
            when = format_relative_time(session["last_message_at"])
            print(f" {i}. {CYAN}{when}{RESET} ({session['messages']} msgs)\n"
                  f"    \"{self._session_preview(session)}\"")

    def _cmd_load(self, arg: str) -> None:
        target = arg.strip()
        sessions = self.agent.store.list_sessions()
        if target.isdigit() and 1 <= int(target) <= len(sessions):
            target = sessions[int(target) - 1]["id"]
        try:
            loaded = self.agent.store.load_messages(target)
            self.agent.messages = [self.agent.messages[0]] + loaded
            self.agent._initial_context_sent = True
            print(f"{GREEN}Loaded {len(loaded)} messages.{RESET}")
        except Exception:
            print(f"{RED}Session not found.{RESET}")

    def _handle_slash(self, raw: str) -> bool:
        """Handle a slash command. Returns False if the REPL should exit."""
        cmd, _, arg = raw.partition(" ")
        if cmd in ("/exit", "/quit"):
            return False
        if cmd == "/help":
            print(self.HELP_TEXT)
        elif cmd == "/sessions":
            self._cmd_sessions()
        elif cmd == "/clear":
            self.agent.messages = [self.agent.messages[0]]
            self.agent._initial_context_sent = False
            print(f"{GREEN}Conversation cleared.{RESET}")
        elif cmd == "/auto":
            self.agent.auto_mode = not self.agent.auto_mode
            print(f"{GREEN}Auto-execute mode: {'ON' if self.agent.auto_mode else 'OFF'}{RESET}")
        elif cmd == "/host":
            new_host = arg.strip()
            if not new_host:
                print(f"{GRAY}Current LLM host: {self.agent.client.host}{RESET}")
            else:
                self.agent.client.host = new_host
                print(f"{GREEN}LLM host changed to: {new_host}{RESET}")
        elif cmd == "/load":
            self._cmd_load(arg)
        return True

    # -- main loop ---------------------------------------------------------------------

    def run(self) -> None:
        self._print_banner()
        while True:
            set_terminal_title(f"❓ {APP_NAME}")
            print(f"\n{GREEN}❯ {RESET}", end="", flush=True)

            block = self._read_block()
            if block is None:
                break
            if not block:
                continue

            if block == "/edit" or block.startswith("/edit "):
                composed = editor_input()
                if not composed:
                    print(f"{GRAY}(empty — discarded){RESET}")
                    continue
                print(f"{GRAY}Composed {len(composed.splitlines())} line(s).{RESET}")
                block = composed  # fall through as a normal request

            if block.startswith("!"):
                self._handle_bang(block)
            elif block.startswith("/"):
                if not self._handle_slash(block):
                    break
            else:
                set_terminal_title(f"⏳ {APP_NAME}")
                try:
                    self.agent.run_turn(block)
                except KeyboardInterrupt:
                    print(f"\n{YELLOW}⚠ Turn interrupted (Ctrl+C). Session preserved. "
                          f"Type a new request or /exit.{RESET}")
                    
        print("\nGoodbye!")
        set_terminal_title("")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    config = parse_config()

    sandbox: Sandbox | None = None
    if config.sandbox:
        sandbox = Sandbox(cpus=config.cpus, memory=config.memory)
        sandbox.start()

    info, limits = resolve_model_and_limits(config)
    client = LLMClient(config.host, config.model, config.temperature, limits)
    agent = Agent(config, client, sandbox=sandbox)

    if config.task:
        agent.run_turn(config.task)
    else:
        setup_readline()
        Repl(agent, model_label(info, limits.window)).run()


if __name__ == "__main__":
    main()
