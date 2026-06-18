"""Terminal rendering utilities: ANSI colors, formatting, highlighting."""

from __future__ import annotations
from __future__ import annotations


import os
import os
import shutil
import shutil
import time
import time


RESET = "\033[0m"
RESET = "\033[0m"
BOLD = "\033[1m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
ITALIC = "\033[3m"
STRIKE = "\033[9m"
STRIKE = "\033[9m"
CLEAR_LINE = "\033[K"
CLEAR_LINE = "\033[K"
THINK_COLOR = "\033[3;90m"
THINK_COLOR = "\033[3;90m"
INLINE_CODE_BG = "\033[48;5;238m"
INLINE_CODE_BG = "\033[48;5;238m"
H1_COLOR = "\033[1;4;38;5;213m"
H1_COLOR = "\033[1;4;38;5;213m"
H2_COLOR = "\033[1;38;5;213m"
H2_COLOR = "\033[1;38;5;213m"
H3_COLOR = "\033[1;38;5;177m"
H3_COLOR = "\033[1;38;5;177m"
CODE_BG = "\033[48;5;236;38;5;253m"
CODE_BG = "\033[48;5;236;38;5;253m"
XML_BG = "\033[48;5;129;38;5;255m"
XML_BG = "\033[48;5;129;38;5;255m"
QUOTE_COLOR = "\033[38;5;245;3m"
QUOTE_COLOR = "\033[38;5;245;3m"
LIST_BULLET = "\033[38;5;214m"
LIST_BULLET = "\033[38;5;214m"
TABLE_BORDER = "\033[38;5;239m"
TABLE_BORDER = "\033[38;5;239m"
LINK_TEXT = "\033[38;5;111;4m"
LINK_TEXT = "\033[38;5;111;4m"
LINK_URL = "\033[38;5;240m"
LINK_URL = "\033[38;5;240m"
SHELL_OUTPUT_BG = "\033[48;5;235;90m"
SHELL_OUTPUT_BG = "\033[48;5;235;90m"




def format_relative_time(ts: float) -> str:
def format_relative_time(ts: float) -> str:
    diff = time.time() - ts
diff = time.time() - ts
    for unit, limit in [("d", 86400), ("h", 3600), ("m", 60)]:
for unit, limit in [("d", 86400), ("h", 3600), ("m", 60)]:
        if diff >= limit:
if diff >= limit:
            return f"{int(diff // limit)}{unit} ago"
return f"{int(diff // limit)}{unit} ago"
    return "just now"
return "just now"




def set_terminal_title(t: str, tmux_window_id: str | None = None) -> None:
def set_terminal_title(t: str, tmux_window_id: str | None = None) -> None:
    print(f"\033]0;{t}\007", end="", flush=True)
print(f"\033]0;{t}\007", end="", flush=True)
    if tmux_window_id:
if tmux_window_id:
        os.system(f"tmux rename-window -t {tmux_window_id} {t!r} 2>/dev/null")
os.system(f"tmux rename-window -t {tmux_window_id} {t!r} 2>/dev/null")




def _get_highlighter(path: str):
def _get_highlighter(path: str):
    ext = os.path.splitext(path)[1].lower()
ext = os.path.splitext(path)[1].lower()
    lang_map = {
lang_map = {
        ".py": "python",
".py": "python",
        ".pyi": "python",
".pyi": "python",
        ".sh": "bash",
".sh": "bash",
        ".bash": "bash",
".bash": "bash",
        ".html": "html",
".html": "html",
        ".htm": "html",
".htm": "html",
    }
}
    lang = lang_map.get(ext)
lang = lang_map.get(ext)
    if not lang:
if not lang:
        return None
return None
    try:
try:
        from highlighters import get_highlighter
from highlighters import get_highlighter
        hl_fn, _ = get_highlighter(lang)
hl_fn, _ = get_highlighter(lang)
        return hl_fn
return hl_fn
    except (KeyError, ImportError):
except (KeyError, ImportError):
        return None
return None




def print_highlighted_content(
def print_highlighted_content(
    content: str, path: str, prefix: str = "+", max_lines: int = 10
content: str, path: str, prefix: str = "+", max_lines: int = 10
) -> None:
) -> None:
    hl_fn = _get_highlighter(path)
hl_fn = _get_highlighter(path)
    lines = content.splitlines()
lines = content.splitlines()


    if hl_fn is not None:
if hl_fn is not None:
        highlighted = hl_fn(content)
highlighted = hl_fn(content)
        for i, line in enumerate(highlighted.splitlines()):
for i, line in enumerate(highlighted.splitlines()):
            if max_lines and i >= max_lines:
if max_lines and i >= max_lines:
                break
break
            print(f"\033[32m{prefix}{RESET}{line}\033[0m")
print(f"\033[32m{prefix}{RESET}{line}\033[0m")
    else:
else:
        for i, line in enumerate(lines):
for i, line in enumerate(lines):
            if max_lines and i >= max_lines:
if max_lines and i >= max_lines:
                break
break
            print(f"\033[32m{prefix}{line}\033[0m")
print(f"\033[32m{prefix}{line}\033[0m")


    if max_lines and len(lines) > max_lines:
if max_lines and len(lines) > max_lines:
        print(f"\033[90m... ({len(lines) - max_lines} more lines)\033[0m")
print(f"\033[90m... ({len(lines) - max_lines} more lines)\033[0m")




def stream_command_output(
def stream_command_output(
    p, color_code: str = "90m"
p, color_code: str = "90m"
) -> tuple[list[str], int]:
) -> tuple[list[str], int]:
    """Stream and display subprocess output line by line with optional coloring."""
"""Stream and display subprocess output line by line with optional coloring."""
    lines: list[str] = []
lines: list[str] = []
    try:
try:
        for l in p.stdout:
for l in p.stdout:
            if not color_code:
if not color_code:
                print(l, end="")
print(l, end="")
            elif color_code == "90m":
elif color_code == "90m":
                w = shutil.get_terminal_size((80, 20)).columns
w = shutil.get_terminal_size((80, 20)).columns
                print(
print(
                    f"{SHELL_OUTPUT_BG}{l.rstrip().ljust(w)}{CLEAR_LINE}{RESET}",
f"{SHELL_OUTPUT_BG}{l.rstrip().ljust(w)}{CLEAR_LINE}{RESET}",
                    end="\n",
end="\n",
                )
)
            else:
else:
                print(f"\033[{color_code}{l.rstrip()}\033[0m", end="\n")
print(f"\033[{color_code}{l.rstrip()}\033[0m", end="\n")
            lines.append(l.rstrip("\n"))
lines.append(l.rstrip("\n"))
        p.wait()
p.wait()
    except KeyboardInterrupt:
except KeyboardInterrupt:
        p.terminate()
p.terminate()
        try:
try:
            p.wait(timeout=2)
p.wait(timeout=2)
        except Exception:
except Exception:
            p.kill()
p.kill()
        lines.append("[Interrupted]")
lines.append("[Interrupted]")
    return lines, p.returncodereturn lines, p.returncode