"""System information utilities."""

from __future__ import annotations

import os
import platform
import sys


def system_summary(sandbox: bool = False) -> dict[str, object]:
    """Collect system info for injection into the initial prompt.

    When *sandbox* is True, returns container-aware info (the actual
    implementation lives in ``localagent.py`` which queries the running
    container via ``docker exec``).  This module is kept as a stable
    public API; callers should prefer ``localagent.system_summary()``.
    """
    cwd = "/workspace" if sandbox else os.getcwd()
    sum_d: dict[str, object] = {
        "os": platform.system(),
        "release": platform.release(),
        "python": sys.version.split()[0],
        "cwd": cwd,
        "shell": os.environ.get("SHELL", ""),
        "user": os.environ.get(
            "USER", os.environ.get("USERNAME", "unknown")
        ),
        "cpu_cores": os.cpu_count() or 0,
    }

    if platform.system() == "Linux":
        try:
            sum_d["memory_total_gb"] = round(
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                / (1024**3),
                1,
            )
        except (ValueError, OSError):
            pass

    return sum_d