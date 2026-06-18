from __future__ import annotations

import shutil
import subprocess
import time


# ANSI color constants
RESET = "\033[0m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
STRIKE = "\033[9m"
CLEAR_LINE = "\033[K"
THINK_COLOR = "\033[3;90m"
INLINE_CODE_BG = "\033[48;5;238m"
H1_COLOR = "\033[1;4;38;5;213m"
H2_COLOR = "\033[1;38;5;213m"
H3_COLOR = "\033[1;38;5;177m"
CODE_BG = "\033[48;5;236;38;5;253m"
XML_BG = "\033[48;5;129;38;5;255m"
QUOTE_COLOR = "\033[38;5;245;3m"
LIST_BULLET = "\033[38;5;214m"
TABLE_BORDER = "\033[38;5;239m"
LINK_TEXT = "\033[38;5;111;4m"
LINK_URL = "\033[38;5;240m"
SHELL_OUTPUT_BG = "\033[48;5;235;90m"

APP_NAME_DISPLAY = "localagent"


def format_relative_time(ts: float) -> str:
    """Format a timestamp as a relative time string."""
    diff = time.time() - ts
    for unit, limit in [("d", 86400), ("h", 3600), ("m", 60)]:
        if diff >= limit:
            return f"{int(diff // limit)}{unit} ago"
    return "just now"


def set_terminal_title(t: str) -> None:
    """Set the terminal window title, including tmux window rename."""
    print(f"\033]0;{t}\007", end="", flush=True)
    try:
        wid = subprocess.check_output("tmux display-message -p '#{window_id}' 2>/dev/null", shell=True, text=True).strip()
        if wid:
            subprocess.run(f"tmux rename-window -t {wid} {t!r} 2>/dev/null", shell=True)
    except Exception:
        pass


class Spinner:
    """Terminal spinner for indicating loading/waiting."""

    def __init__(self):
        import threading
        self.stop_event = threading.Event()

    def start(self):
        import threading

        def spin():
            i = 0
            while not self.stop_event.is_set():
                print(f"\r\033[90m{"|/-\\"[i % 4]} \033[0m", end="", flush=True)
                i += 1
                time.sleep(0.1)

        threading.Thread(target=spin, daemon=True).start()

    def stop(self):
        self.stop_event.set()
        print(f"\r{CLEAR_LINE}", end="", flush=True)