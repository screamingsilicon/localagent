"""File editing actions for localagent.

Handles <edit> and <write> XML action execution with syntax checking,
diff display, approval prompts, and escape-path warnings.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any


def _is_path_escape(cwd: str, target: str) -> bool:
    """Check if a target path escapes the cwd boundary."""
    return not (Path(cwd) / Path(target).expanduser()).resolve().is_relative_to(Path(cwd))


def _print_diff(diff: str):
    """Print a colored diff to stdout."""
    print(f"\033[36mProposed changes:\033[0m")
    for line in diff.splitlines():
        color = "32m" if line.startswith("+") else ("31m" if line.startswith("-") else "90m")
        print(f"\033[{color}{line}\033[0m")


def _count_diff_lines(diff: str) -> tuple[int, int]:
    """Count added and removed lines in a diff string."""
    return (
        sum(1 for l in diff.splitlines() if l.startswith("-")),
        sum(1 for l in diff.splitlines() if l.startswith("+")),
    )


def execute_edit(act: dict, cwd: str, auto_mode: bool, sandbox: bool, log_tool_call=None) -> str:
    """Execute an edit action on a file."""
    from file_ops import read_file, write_file, check_syntax, format_diff, find_and_replace, normalize_text

    path, rem, f_txt, r_txt = act["path"], act["remote"], act["find"], act["replace"]

    content, err = read_file(path, cwd, rem, sandbox=sandbox)
    if err == "path_escapes":
        escape_path = Path(cwd, Path(path).expanduser()).resolve()
        print(f"\033[33m⚠ [Edit] Path escapes repo boundary: {escape_path}\033[0m")

        content, err = read_file(path, cwd, rem, allow_escape=True, sandbox=sandbox)
        if err:
            if log_tool_call: log_tool_call("edit", False, {"err": err})
            return f"Error reading {path}: {err}"

    elif err:
        if log_tool_call: log_tool_call("edit", False, {"err": err})
        return f"Error reading {path}: {err}"

    # Common edit logic (shared by both normal and escape-path branches)
    try:
        base, new, start_line, end_line = find_and_replace(
            normalize_text(content if content != "[empty]" else "", strict=True),
            f_txt, r_txt, path, strict=bool(rem)
        )
    except Exception as e:
        if log_tool_call: log_tool_call("edit", False, {"err": str(e)})
        return f"Edit failed: {e}"

    # Syntax check
    ok = check_syntax(path, new)
    if not ok[0]:
        if log_tool_call: log_tool_call("edit", False, {"err": ok[1]})
        return f"Syntax Error: {ok[1]}"

    diff = format_diff(base, new)
    n_removed, n_added = _count_diff_lines(diff)

    # Approval prompt (only for escape paths when not in auto mode)
    if _is_path_escape(cwd, path) and not auto_mode:
        from display import BOLD, RESET
        _print_diff(diff)
        print(f"{BOLD}(Approve? y/n): {RESET}", end="", flush=True)
        try:
            if input().strip().lower() != 'y':
                if log_tool_call: log_tool_call("edit", False, {"denied": True, "path": path})
                return "Denied by user."
        except KeyboardInterrupt:
            if log_tool_call: log_tool_call("edit", False, {"denied": True, "path": path})
            return "Denied by user."

    # Write the file
    allow_escape = _is_path_escape(cwd, path)
    if write_err := write_file(path, new, cwd, rem, allow_escape=allow_escape, sandbox=sandbox):
        if log_tool_call: log_tool_call("edit", False, {"err": write_err})
        return f"Write failed: {write_err}"

    print(f"\033[36m[Edit] {rem or 'local'} -> {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines\033[0m")

    if log_tool_call:
        log_tool_call("edit", True, {"path": path})
    return f"Successfully edited {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines"


def execute_write(act: dict, cwd: str, auto_mode: bool, sandbox: bool, log_tool_call=None) -> str:
    """Execute a write action to create/overwrite a file."""
    from file_ops import write_file, check_syntax
    from display import BOLD, RESET

    path, rem, content = act["path"], act["remote"], act["content"]
    if not path:
        return "Error: missing 'path'."
    if not (ok := check_syntax(path, content))[0]:
        if log_tool_call: log_tool_call("write", False, {"err": ok[1], "path": path})
        return f"Syntax Error: {ok[1]}"

    n_lines = len(content.splitlines())

    if _is_path_escape(cwd, path):
        escape_path = Path(cwd, Path(path).expanduser()).resolve()
        print(f"\033[33m⚠ [Write] Path escapes repo boundary: {escape_path}\033[0m")
        print(f"\033[36mProposed file content ({n_lines} lines):\033[0m")
        _print_highlighted_content(content, path, prefix="+", max_lines=10)

        if not auto_mode:
            print(f"{BOLD}(Approve? y/n): {RESET}", end="", flush=True)
            try:
                if input().strip().lower() != 'y':
                    if log_tool_call: log_tool_call("write", False, {"denied": True, "path": path})
                    return "Denied by user."
            except KeyboardInterrupt:
                if log_tool_call: log_tool_call("write", False, {"denied": True, "path": path})
                return "Denied by user."

        if err := write_file(path, content, cwd, rem, allow_escape=True, sandbox=sandbox):
            if log_tool_call: log_tool_call("write", False, {"err": err})
            return f"Write failed: {err}"

        print(f"\033[36m[Write] Wrote {n_lines} lines to {path}\033[0m")
    else:
        if err := write_file(path, content, cwd, rem, sandbox=sandbox):
            if log_tool_call: log_tool_call("write", False, {"err": err})
            return f"Write failed: {err}"

        print(f"\033[36m[Write] Wrote {n_lines} lines to {path}\033[0m")

    if log_tool_call:
        log_tool_call("write", True, {"path": path})
    return f"Wrote content to {path}"


def _print_highlighted_content(content: str, filename: str, prefix: str = "+", max_lines: int = 10):
    """Print file content with syntax highlighting and line prefixes."""
    from highlighters import get_highlighter

    hl = get_highlighter(filename)
    lines = content.splitlines()
    for i, line in enumerate(lines[:max_lines], 1):
        highlighted = hl(line) if hl else line
        print(f"{prefix}\033[90m{i:4d}\033[0m{highlighted}")
    if len(lines) > max_lines:
        print(f"\033[90m  ... and {len(lines) - max_lines} more lines\033[0m")