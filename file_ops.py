
"""File read/write/edit primitives for localagent.

Handles local, SSH-remote, and Docker-sandbox file operations, plus
text normalization, find-and-replace, syntax checking, and diff formatting.
"""

from __future__ import annotations

import ast
import os
import random
import re
import stat
import subprocess
import unicodedata
from difflib import unified_diff
from pathlib import Path
from typing import Optional


MAX_FILE_SIZE = 256 * 1024  




# UTF-8 BOM marker — strip before matching so models don't need to include it
_BOM = "\ufeff"


def strip_bom(text: str) -> tuple[str, bool]:
    """Strip leading BOM if present. Returns (text, had_bom)."""
    if text.startswith(_BOM):
        return text[len(_BOM):], True
    return text, False


# Pre-compiled regex patterns for fuzzy normalization (avoid per-call import overhead)
_RE_SMART_SINGLE_QUOTE = re.compile(r"[\u2018\u2019\u201a\u201b]")
_RE_SMART_DOUBLE_QUOTE = re.compile(r"[\u201c\u201d\u201e\u201f]")
_RE_UNICODE_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_RE_SPECIAL_SPACES = re.compile(r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]")


def _normalize_lf_only(text: str) -> str:
    """Normalize only line endings (CRLF/CR → LF). No BOM stripping."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_trailing_ws(text: str) -> str:
    """Strip trailing whitespace from each line. Preserves all else."""
    return "\n".join(line.rstrip() for line in text.split("\n"))


def _normalize_unicode_chars(text: str) -> str:
    """Normalize Unicode quotes/dashes/spaces to ASCII equivalents."""
    text = _RE_SMART_SINGLE_QUOTE.sub("'", text)
    text = _RE_SMART_DOUBLE_QUOTE.sub('"', text)
    text = _RE_UNICODE_DASHES.sub("-", text)
    text = _RE_SPECIAL_SPACES.sub(" ", text)
    return text


def normalize_text(text: str, strict: bool = False) -> str:
    """Normalize line endings, Unicode quotes/dashes, and trailing whitespace.

    Also strips a leading UTF-8 BOM so that find-and-replace matching is
    reliable regardless of whether the model includes the invisible marker.

    Args:
        text: Raw input text.
        strict: If True, only normalize line endings (no whitespace stripping).

    Returns:
        Normalized text with NFKC Unicode normalization.
    """
    # Strip BOM first — models never include it in <find> blocks
    text, _ = strip_bom(text)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict:
        return text
    text = "\n".join(
        line.rstrip() for line in unicodedata.normalize("NFKC", text).split("\n")
    )
    text = _RE_SMART_SINGLE_QUOTE.sub("'", text)
    text = _RE_SMART_DOUBLE_QUOTE.sub('"', text)
    text = _RE_UNICODE_DASHES.sub("-", text)
    text = _RE_SPECIAL_SPACES.sub(" ", text)
    return text


class FuzzyMatchResult:
    """Result of a fuzzy match attempt, tracking what normalization was needed."""
    __slots__ = ("found", "index", "match_length", "strategy", "content_for_replace")

    def __init__(self, found: bool, index: int = -1, match_length: int = 0,
                 strategy: str = "none", content_for_replace: str | None = None):
        self.found = found
        self.index = index
        self.match_length = match_length
        self.strategy = strategy
        self.content_for_replace = content_for_replace

    @staticmethod
    def not_found() -> "FuzzyMatchResult":
        return FuzzyMatchResult(found=False)

    @staticmethod
    def matched(index: int, match_length: int, strategy: str,
                content_for_replace: str | None = None) -> "FuzzyMatchResult":
        return FuzzyMatchResult(
            found=True, index=index, match_length=match_length,
            strategy=strategy, content_for_replace=content_for_replace,
        )


def _count_occurrences(content: str, search: str, normalize_fn) -> int:
    """Count occurrences of search in content after normalization."""
    norm_content = normalize_fn(content)
    norm_search = normalize_fn(search)
    return norm_content.count(norm_search)


def fuzzy_find(text: str, pattern: str) -> FuzzyMatchResult:
    """Find *pattern* in *text* using progressive fallback strategies.

    Tries increasingly aggressive normalization:
      1. Exact match (fastest, most precise)
      2. LF-only normalized (handles CRLF vs LF differences)
      3. Trailing whitespace tolerant (strips trailing spaces per line)
      4. Full fuzzy (Unicode quotes/dashes/spaces + trailing whitespace)

    Args:
        text: The full file content to search in.
        pattern: The text to find (from the model's <find> block).

    Returns:
        FuzzyMatchResult with match position, length, and strategy used.
    """
    # Strategy 1: Exact match
    exact_idx = text.find(pattern)
    if exact_idx != -1:
        return FuzzyMatchResult.matched(exact_idx, len(pattern), "exact", text)

    # Strategy 2: LF-only normalization (CRLF/CR → LF)
    lf_text = _normalize_lf_only(text)
    lf_pattern = _normalize_lf_only(pattern)
    if lf_text != text or lf_pattern != pattern:
        idx = lf_text.find(lf_pattern)
        if idx != -1:
            return FuzzyMatchResult.matched(idx, len(lf_pattern), "lf-normalized", lf_text)

    # Strategy 3: Trailing whitespace tolerant
    ws_text = _normalize_trailing_ws(text)
    ws_pattern = _normalize_trailing_ws(pattern)
    if ws_text != text or ws_pattern != pattern:
        idx = ws_text.find(ws_pattern)
        if idx != -1:
            return FuzzyMatchResult.matched(idx, len(ws_pattern), "trailing-ws", ws_text)

    # Strategy 4: Full fuzzy normalization (Unicode chars + trailing whitespace)
    norm_text = normalize_text(text)
    norm_pattern = normalize_text(pattern)
    idx = norm_text.find(norm_pattern)
    if idx != -1:
        return FuzzyMatchResult.matched(idx, len(norm_pattern), "full-fuzzy", norm_text)

    return FuzzyMatchResult.not_found()


def _get_fuzzy_error(path: str, strategy_hint: str | None = None) -> str:
    """Build a helpful error message for fuzzy match failure."""
    hints = []
    if strategy_hint == "trailing-ws":
        hints.append("Check trailing whitespace on each line.")
    elif strategy_hint == "lf-normalized":
        hints.append("The file may use different line endings (CRLF vs LF).")
    elif strategy_hint == "full-fuzzy":
        hints.append(
            "The text may contain Unicode characters (smart quotes, dashes, special spaces) "
            "that look identical but don't match exactly."
        )
    hint_str = f" {hints[0]}" if hints else ""
    return f"Text not found in {path}.{hint_str} Ensure the <find> block matches exactly."


def check_syntax(path: str, content: str) -> tuple[bool, str | None]:
    """Check Python syntax of *content* when *path* ends with '.py'.

    Returns (True, None) for non-Python files or valid Python.
    Returns (False, error_message) for Python syntax errors.
    """
    if not path.endswith(".py"):
        return True, None
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, str(e)


def format_diff(old_str: str, new_str: str, ctx: int = 1) -> str:
    """Produce a unified diff string between *old_str* and *new_str*.

    Hides the @@ hunk headers (replaces them with ' ...') and omits
    the --- / +++ file-header lines.
    """
    RESET = "\033[0m"  
    diff = unified_diff(
        old_str.splitlines(), new_str.splitlines(), n=ctx, lineterm=""
    )
    return "\n".join(
        f" {RESET} ..." if l.startswith("@@") else l
        for l in diff
        if not l.startswith(("---", "+++"))
    )


def find_and_replace(
    content: str,
    old_text: str,
    new_text: str,
    path: str,
    strict: bool = False,
) -> tuple[str, str, int, int]:
    """Find *old_text* in *content* and replace with *new_text*.

    Uses progressive fuzzy matching: exact → LF-normalized → trailing whitespace
    tolerant → full Unicode normalization. Falls back to increasingly aggressive
    strategies only when the previous one fails.

    Args:
        content: Full file contents.
        old_text: Text to find (exact or fuzzy depending on *strict*).
        new_text: Replacement text.
        path: File path (used in error messages).
        strict: If True, require exact match only (no fuzzy fallbacks).

    Returns:
        (base_content, new_content, start_line, end_line)

    Raises:
        ValueError: If old_text is empty, not found, or matches multiple times.
    """
    if not old_text:
        raise ValueError("oldText empty")

    # Strategy 1: Exact match (always tried first, required in strict mode)
    exact_idx = content.find(old_text)
    if exact_idx != -1:
        if content.count(old_text) > 1:
            raise ValueError("Multiple exact matches found.")
        start_line = content[:exact_idx].count("\n") + 1
        end_line = content[exact_idx:exact_idx + len(old_text)].count("\n") + start_line
        new_content = content[:exact_idx] + new_text + content[exact_idx + len(old_text):]
        return content, new_content, start_line, end_line

    # Strict mode: no fuzzy fallbacks
    if strict:
        raise ValueError(
            f"Text not found in {path}. Provide an exact match "
            "(including whitespace/indentation)."
        )

    # Try progressive fuzzy matching (non-strict mode only)
    result = fuzzy_find(content, old_text)

    if not result.found:
        raise ValueError(_get_fuzzy_error(path))

    # Check for uniqueness in the matched content space
    base_content = result.content_for_replace or content
    norm_fn = {
        "lf-normalized": _normalize_lf_only,
        "trailing-ws": _normalize_trailing_ws,
        "full-fuzzy": normalize_text,
    }.get(result.strategy, lambda x: x)

    if _count_occurrences(base_content, old_text, norm_fn) > 1:
        raise ValueError("Multiple fuzzy matches found.")

    # Calculate line numbers in the base content
    start_line = base_content[:result.index].count("\n") + 1
    end_line = base_content[result.index:result.index + result.match_length].count("\n") + start_line

    # Apply the replacement in the matched content space
    new_content = (
        base_content[:result.index] + new_text + base_content[result.index + result.match_length:]
    )

    return base_content, new_content, start_line, end_line




def _is_path_escape(cwd: str, path: str) -> bool:
    """Check whether *path* resolves outside *cwd*."""
    try:
        resolved = Path(cwd, Path(path).expanduser()).resolve()
        return not resolved.is_relative_to(Path(cwd).resolve())
    except Exception:
        return True




def read_file(
    path: str,
    base_dir: str,
    remote: str | None = None,
    allow_escape: bool = False,
    sandbox: bool = False,
) -> tuple[str | None, str | None]:
    """Read a file from local disk, SSH host, or Docker sandbox.

    Args:
        path: Target file path (relative or absolute).
        base_dir: Working directory for relative paths.
        remote: SSH destination (e.g. 'user@host') — overrides local/sandbox.
        allow_escape: Permit reading files outside *base_dir*.
        sandbox: If True, read through Docker exec instead of local FS.

    Returns:
        (content, error). On success *error* is ``None``; on failure
        *content* is ``None`` and *error* describes the problem.
    """
    
    if remote:
        p = subprocess.run(
            f"ssh {remote} \"cat '{path}'\"",
            shell=True, capture_output=True, text=True,
        )
        return (p.stdout, None) if p.returncode == 0 else (None, p.stderr.strip())

    
    if sandbox:
        try:
            from docker_sandbox import docker_exec_read_file
        except ImportError:
            return None, "docker_sandbox not available"
        resolved = Path(path).resolve(strict=False)
        rel = os.path.relpath(resolved, "/workspace")
        cpath = f"/workspace/{rel}"
        content, err = docker_exec_read_file(cpath)
        if err:
            return None, "not found"
        if not content:
            return "[empty]", None
        return content, None

    
    try:
        p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
        base_resolved = Path(base_dir).resolve()
        if not allow_escape and not p.is_relative_to(base_resolved):
            return None, "path_escapes"
        if not p.exists():
            return None, "not found"
        if p.is_symlink():
            resolved_link = p.resolve()
            if not allow_escape and not resolved_link.is_relative_to(base_resolved):
                return None, "symlink escapes repo boundary"
        if not stat.S_ISREG(p.stat().st_mode):
            return None, "not a regular file"
        if p.stat().st_size > MAX_FILE_SIZE:
            return None, "file too large"
        content = p.read_text(encoding="utf-8")
        return content if content else "[empty]", None
    except UnicodeDecodeError:
        return None, "binary/not UTF-8"
    except Exception as e:
        return None, str(e)




def write_file(
    path: str,
    content: str,
    base_dir: str,
    remote: str | None = None,
    allow_escape: bool = False,
    sandbox: bool = False,
) -> str | None:
    """Write *content* to *path* on local disk, SSH host, or Docker sandbox.

    Args:
        path: Target file path.
        content: File contents to write.
        base_dir: Working directory for relative paths.
        remote: SSH destination — overrides local/sandbox.
        allow_escape: Permit writing files outside *base_dir*.
        sandbox: If True, write through Docker exec instead of local FS.

    Returns:
        ``None`` on success, or an error message string on failure.
    """
    
    if remote:
        tmp = f"{path}.tmp.{random.randint(100000, 999999)}"
        p = subprocess.run(
            f"ssh {remote} \"cat > '{tmp}' && mv '{tmp}' '{path}'\"",
            shell=True, input=content, text=True, capture_output=True,
        )
        return p.stderr.strip() if p.returncode != 0 else None

    
    if sandbox:
        try:
            from docker_sandbox import (
                docker_exec_file_write,
                get_container_name,
            )
        except ImportError:
            return "docker_sandbox not available"
        resolved = Path(path).resolve(strict=False)
        rel = os.path.relpath(resolved, "/workspace")
        cpath = f"/workspace/{rel}"
        subprocess.run(
            [
                "docker", "exec", "-i", get_container_name(),
                "sh", "-c", f"mkdir -p '{os.path.dirname(cpath)}'",
            ],
            capture_output=True,
        )
        rc = docker_exec_file_write(cpath, content)
        return None if rc == 0 else "write failed"

    
    try:
        p = Path(base_dir, Path(path).expanduser()).resolve(strict=False)
        base_resolved = Path(base_dir).resolve()
        if not allow_escape and not p.is_relative_to(base_resolved):
            return "path_escapes"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return None
    except Exception as e:
        return str(e)