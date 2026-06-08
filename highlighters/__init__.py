"""Syntax highlighters for Python, Bash, and HTML.

Usage:
    from highlighters import highlight_python, highlight_bash, highlight_html
    from highlighters import diff_highlight_python, diff_highlight_bash, diff_highlight_html
    from highlighters import get_highlighter  # returns the right highlighter by language name
"""

from __future__ import annotations

from .python import (
    highlight as highlight_python,
    diff_highlight as diff_highlight_python,
)
from .bash import (
    BashScanner,
    _highlight as highlight_bash,
    _diff_highlight as diff_highlight_bash,
)
from .html import (
    highlight as highlight_html,
    diff_highlight as diff_highlight_html,
)

__all__ = [
    "highlight_python",
    "diff_highlight_python",
    "highlight_bash",
    "diff_highlight_bash",
    "highlight_html",
    "diff_highlight_html",
    "BashScanner",
    "get_highlighter",
]


_LANG_MAP: dict[str, tuple] = {
    "python":      (highlight_python, diff_highlight_python),
    "py":          (highlight_python, diff_highlight_python),
    "bash":        (highlight_bash,   diff_highlight_bash),
    "sh":          (highlight_bash,   diff_highlight_bash),
    "shell":       (highlight_bash,   diff_highlight_bash),
    "html":        (highlight_html,   diff_highlight_html),
    "htm":         (highlight_html,   diff_highlight_html),
}


def get_highlighter(lang: str):
    """Return (highlight_fn, diff_highlight_fn) for the given language name.

    Raises KeyError if *lang* is not recognised.
    """
    return _LANG_MAP[lang.lower()]