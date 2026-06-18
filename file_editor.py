from __future__ import annotations

import os
from pathlib import Path


def _is_path_escape(cwd: str, path: str) -> bool:
    """Check if a resolved path escapes the working directory."""
    from file_ops import _is_path_escape as _ipe
    return _ipe(cwd, path)


def _get_highlighter(path: str):
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
    from display import RESET

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


def execute_edit(act: dict, cwd: str, auto_mode: bool, sandbox: bool, log_tool_call=None) -> str:
    """Execute an edit action on a file."""
    from file_ops import read_file, write_file, normalize_text, find_and_replace, check_syntax, format_diff
    from display import BOLD, RESET

    path, rem, f_txt, r_txt = act["path"], act["remote"], act["find"], act["replace"]

    content, err = read_file(path, cwd, rem, sandbox=sandbox)
    if err == "path_escapes":
        escape_path = Path(cwd, Path(path).expanduser()).resolve()
        print(f"\033[33m⚠ [Edit] Path escapes repo boundary: {escape_path}\033[0m")

        content, err = read_file(path, cwd, rem, allow_escape=True, sandbox=sandbox)
        if err:
            if log_tool_call: log_tool_call("edit", False, {"err": err})
            return f"Error reading {path}: {err}"

        try:
            base, new, start_line, end_line = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
            if not (ok := check_syntax(path, new))[0]:
                if log_tool_call: log_tool_call("edit", False, {"err": ok[1]})
                return f"Syntax Error: {ok[1]}"

            diff = format_diff(base, new)
            print(f"\033[36mProposed changes:\033[0m")
            for l in diff.splitlines():
                print(f"\033[{'32m' if l.startswith('+') else '31m' if l.startswith('-') else '90m'}{l}\033[0m")

            if not auto_mode:
                print(f"{BOLD}(Approve? y/n): {RESET}", end="", flush=True)
                try:
                    if input().strip().lower() != 'y':
                        if log_tool_call: log_tool_call("edit", False, {"denied": True, "path": path})
                        return "Denied by user."
                except KeyboardInterrupt:
                    if log_tool_call: log_tool_call("edit", False, {"denied": True, "path": path})
                    return "Denied by user."

            if err := write_file(path, new, cwd, rem, allow_escape=True, sandbox=sandbox):
                if log_tool_call: log_tool_call("edit", False, {"err": err})
                return f"Write failed: {err}"
            n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
            n_added = sum(1 for l in diff.splitlines() if l.startswith("+"))
            print(f"\033[36m[Edit] {rem or 'local'} -> {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines\033[0m")
        except Exception as e:
            if log_tool_call: log_tool_call("edit", False, {"err": str(e)})
            return f"Edit failed: {e}"

    elif err:
        if log_tool_call: log_tool_call("edit", False, {"err": err})
        return f"Error reading {path}: {err}"

    else:
        try:
            base, new, start_line, end_line = find_and_replace(normalize_text(content if content != "[empty]" else "", strict=True), f_txt, r_txt, path, strict=bool(rem))
            if not (ok := check_syntax(path, new))[0]:
                if log_tool_call: log_tool_call("edit", False, {"err": ok[1]})
                return f"Syntax Error: {ok[1]}"

            diff = format_diff(base, new)
            n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
            n_added = sum(1 for l in diff.splitlines() if l.startswith("+"))
            print(f"\033[36m[Edit] {rem or 'local'} -> {path}: lines {start_line}-{end_line} | replaced {n_removed} lines with {n_added} lines\033[0m")

            if err := write_file(path, new, cwd, rem, sandbox=sandbox):
                if log_tool_call: log_tool_call("edit", False, {"err": err})
                return f"Write failed: {err}"
        except Exception as e:
            if log_tool_call: log_tool_call("edit", False, {"err": str(e)})
            return f"Edit failed: {e}"

    if log_tool_call:
        log_tool_call("edit", True, {"path": path})
    n_removed = sum(1 for l in diff.splitlines() if l.startswith("-"))
    n_added = sum(1 for l in diff.splitlines() if l.startswith("+"))
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