"""JSON syntax highlighter using regex-based tokenisation."""

from __future__ import annotations

import re


C = {
    "key":        "\033[1;36m",
    "string":     "\033[33m",
    "number":     "\033[1;96m",
    "boolean":    "\033[1;95m",
    "null":       "\033[1;37;41m",
    "punct":      "\033[90m",
    "trailing":   "\033[1;31m",
    "reset":      "\033[0m",
}

# JSON keywords are always lowercase
JSON_KEYWORDS = {"true", "false", "null"}


def _colorize_token(match: re.Match) -> str:
    """Return the coloured string for a single regex match."""
    kind = match.lastgroup
    val = match.group(kind)

    if kind == "string_key":
        return C["key"] + val + C["reset"]

    if kind == "string_val":
        return C["string"] + val + C["reset"]

    if kind == "number":
        return C["number"] + val + C["reset"]

    if kind == "keyword":
        kw = val.lower()
        if kw == "null":
            return C["null"] + val + C["reset"]
        return C["boolean"] + val + C["reset"]

    if kind in ("comma", "colon", "braces", "brackets"):
        return C["punct"] + val + C["reset"]

    # Whitespace and other -- pass through unchanged
    return val


# Token regex ordered by priority:
# 1. Keys (strings followed by colon -- must not consume the colon)
# 2. String values
# 3. Numbers
# 4. Keywords (true/false/null)
# 5. Punctuation
# 6. Whitespace
_TOKEN_RE = re.compile(
    r"""(?P<string_key>"(?:[^"\\]|\\.)*")(?=\s*:)"""   # "key" (lookahead for optional ws + colon, don't consume)
    r'|(?P<string_val>"(?:[^"\\]|\\.)*")'                  # "value"
    r'|(?P<number>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\b'  # numbers
    r'|(?P<keyword>true|false|null)\b'                     # booleans & null
    r'|(?P<comma>,)'                                       # ,
    r'|(?P<colon>:)'                                       # :
    r'|(?P<braces>[{}])'                                   # { }
    r'|(?P<brackets>[\[\]])'                               # [ ]
    r'|(?P<ws>\s+)'                                        # whitespace
)


def highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-coloured version of JSON text.

    Parameters
    ----------
    source : str
        JSON source text (may be well-formed or malformed).
    show_trailing : bool
        If True, visualise trailing whitespace with \u00b7 and \u2192 markers.

    Returns
    -------
    str
        ANSI-coloured version of the input.
    """
    if not source:
        return ""

    lines = source.splitlines(True)
    result_parts: list[str] = []

    for line in lines:
        coloured_line = _colorize_line(line)
        if show_trailing:
            coloured_line = _visualize_trailing(coloured_line, line)
        result_parts.append(coloured_line)

    return "".join(result_parts)


def _colorize_line(line: str) -> str:
    """Colorize a single JSON line."""
    parts: list[str] = []
    pos = 0

    for m in _TOKEN_RE.finditer(line):
        if m.start() > pos:
            parts.append(line[pos:m.start()])
        parts.append(_colorize_token(m))
        pos = m.end()

    if pos < len(line):
        parts.append(line[pos:])

    return "".join(parts)


def _visualize_trailing(coloured: str, original_line: str) -> str:
    """Add visual markers for trailing whitespace on a line."""
    stripped = original_line.rstrip()
    trailing = original_line[len(stripped):]
    if not trailing:
        return coloured

    vis = re.sub(r' ', '\u00b7', trailing)
    vis = re.sub(r'\t', '\u2192', vis)
    line_end = "\n" if original_line.endswith("\n") else ""
    without_newline = coloured.rstrip("\n")
    return without_newline + C["trailing"] + vis + C["reset"] + line_end


def diff_highlight(
    old_source: str,
    new_source: str,
    old_label: str = "old",
    new_label: str = "new",
    context_lines: int = 3,
) -> str:
    """Produce a syntax-highlighted unified diff between two JSON sources.

    Parameters
    ----------
    old_source / new_source : plain-text JSON sources.
    old_colored / new_colored : pre-highlighted versions (auto-generated).
    old_label / new_label : labels shown in the diff header.
    context_lines : number of context lines around changes.

    Returns
    -------
    str
        ANSI-coloured unified diff string.
    """
    from .differ import diff_highlight as _raw_diff

    old_colored = highlight(old_source)
    new_colored = highlight(new_source)

    return _raw_diff(
        old_source, new_source,
        old_colored=old_colored, new_colored=new_colored,
        old_label=old_label, new_label=new_label,
        context_lines=context_lines,
    )
