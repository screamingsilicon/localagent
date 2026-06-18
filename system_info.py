"""System information utilities."""

from __future__ import annotations
from __future__ import annotations


import os
import os
import platform
import platform
import sys
import sys




def system_summary(sandbox: bool = False) -> dict[str, object]:
def system_summary(sandbox: bool = False) -> dict[str, object]:
    """Collect host system info for injection into the initial prompt."""
"""Collect host system info for injection into the initial prompt."""
    cwd = "/workspace" if sandbox else os.getcwd()
cwd = "/workspace" if sandbox else os.getcwd()
    sum_d: dict[str, object] = {
sum_d: dict[str, object] = {
        "os": platform.system(),
"os": platform.system(),
        "release": platform.release(),
"release": platform.release(),
        "python": sys.version.split()[0],
"python": sys.version.split()[0],
        "cwd": cwd,
"cwd": cwd,
        "shell": os.environ.get("SHELL", ""),
"shell": os.environ.get("SHELL", ""),
        "user": os.environ.get(
"user": os.environ.get(
            "USER", os.environ.get("USERNAME", "unknown")
"USER", os.environ.get("USERNAME", "unknown")
        ),
),
        "cpu_cores": os.cpu_count() or 0,
"cpu_cores": os.cpu_count() or 0,
    }
}


    if platform.system() == "Linux":
if platform.system() == "Linux":
        try:
try:
            sum_d["memory_total_gb"] = round(
sum_d["memory_total_gb"] = round(
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                / (1024**3),
/ (1024**3),
                1,
1,
            )
)
        except (ValueError, OSError):
except (ValueError, OSError):
            pass
pass


    return sum_dreturn sum_d