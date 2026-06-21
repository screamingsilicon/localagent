"""Syntax highlighters for Python, Bash, HTML, JSON, YAML, SQL, and JavaScript.

Usage:
    from highlighters import highlight_python, highlight_bash, highlight_html
    from highlighters import diff_highlight_python, diff_highlight_bash, diff_highlight_html
    from highlighters import highlight_json, diff_highlight_json
    from highlighters import highlight_yaml, diff_highlight_yaml
    from highlighters import highlight_sql, diff_highlight_sql
    from highlighters import highlight_javascript, diff_highlight_javascript
    from highlighters import get_highlighter
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
from .json import (
    highlight as highlight_json,
    diff_highlight as diff_highlight_json,
)
from .yaml import (
    highlight as highlight_yaml,
    diff_highlight as diff_highlight_yaml,
)
from .sql import (
    highlight as highlight_sql,
    diff_highlight as diff_highlight_sql,
)
from .javascript import (
    highlight as highlight_javascript,
    diff_highlight as diff_highlight_javascript,
)

__all__ = [
    "highlight_python",
    "diff_highlight_python",
    "highlight_bash",
    "diff_highlight_bash",
    "highlight_html",
    "diff_highlight_html",
    "highlight_json",
    "diff_highlight_json",
    "highlight_yaml",
    "diff_highlight_yaml",
    "highlight_sql",
    "diff_highlight_sql",
    "highlight_javascript",
    "diff_highlight_javascript",
    "BashScanner",
    "get_highlighter",
]


_LANG_MAP: dict[str, tuple] = {
    "python":         (highlight_python, diff_highlight_python),
    "py":             (highlight_python, diff_highlight_python),
    "bash":           (highlight_bash,   diff_highlight_bash),
    "sh":             (highlight_bash,   diff_highlight_bash),
    "shell":          (highlight_bash,   diff_highlight_bash),
    "html":           (highlight_html,   diff_highlight_html),
    "htm":            (highlight_html,   diff_highlight_html),
    "json":           (highlight_json,   diff_highlight_json),
    "yaml":           (highlight_yaml,   diff_highlight_yaml),
    "yml":            (highlight_yaml,   diff_highlight_yaml),
    "sql":            (highlight_sql,    diff_highlight_sql),
    "javascript":     (highlight_javascript, diff_highlight_javascript),
    "js":             (highlight_javascript, diff_highlight_javascript),
}


def get_highlighter(lang: str):
    """Return (highlight_fn, diff_highlight_fn) for the given language name.

    Raises KeyError if *lang* is not recognised.
    """
    return _LANG_MAP[lang.lower()]