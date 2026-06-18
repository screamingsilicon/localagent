
"""File read/write/edit primitives for localagent.

Handles local, SSH-remote, and Docker-sandbox file operations, plus
text normalization, find-and-replace, syntax checking, and diff formatting.
"""

from __future__ import annotations

import ast
import os
import random
import stat
import subprocess
import unicodedata
from difflib import unified_diff
from pathlib import Path
from typing import Optional


MAX_FILE_SIZE = 256 * 1024  




def normalize_text(text: str, strict: bool = False) -> str:
    """Normalize line endings, Unicode quotes/dashes, and trailing whitespace.

    Args:
        text: Raw input text.
        strict: If True, only normalize line endings (no whitespace stripping).

    Returns:
        Normalized text with NFKC Unicode normalization.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if strict:
        return text
    text = "\n".join(
        line.rstrip() for line in unicodedata.normalize("NFKC", text).split("\n")
    )
    for pat, rep in [
        (r"[\u2018\u2019\u201a\u201b]", "'"),
        (r"[\u201c\u201d\u201e\u201f]", '"'),
        (r"[\u2010-\u2015\u2212]", "-"),
        (r"[\u00a0\u2002-\u200a\u202f\u205f\u3000]", " "),
    ]:
        text = __import__("re").sub(pat, rep, text)
    return text


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

    Args:
        content: Full file contents.
        old_text: Text to find (exact or fuzzy depending on *strict*).
        new_text: Replacement text.
        path: File path (used in error messages).
        strict: If True, require exact match (no normalization).

    Returns:
        (base_content, new_content, start_line, end_line)

    Raises:
        ValueError: If old_text is empty, not found, or matches multiple times.
    """
    if not old_text:
        raise ValueError("oldText empty")

    
    exact_idx = content.find(old_text)
    if exact_idx != -1:
        if content.count(old_text) > 1:
            raise ValueError("Multiple exact matches found.")
        start_line = content[:exact_idx].count("\n") + 1
        end_line = content[exact_idx : exact_idx + len(old_text)].count("\n") + start_line
        new_content = content[:exact_idx] + new_text + content[exact_idx + len(old_text) :]
        return content, new_content, start_line, end_line

    
    if strict:
        raise ValueError(
            f"Text not found in {path}. Provide an exact match "
            "(including whitespace/indentation)."
        )
    base = normalize_text(content)
    norm_old = normalize_text(old_text)
    norm_idx = base.find(norm_old)
    if norm_idx == -1:
        raise ValueError(
            f"Text not found in {path}. Check whitespace/indentation."
        )
    if base.count(norm_old) > 1:
        raise ValueError("Multiple fuzzy matches found.")
    start_line = base[:norm_idx].count("\n") + 1
    end_line = base[norm_idx : norm_idx + len(norm_old)].count("\n") + start_line
    new_content = (
        base[:norm_idx] + new_text + base[norm_idx + len(norm_old) :]
    )
    return base, new_content, start_line, end_line




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