"""YAML syntax highlighter using regex-based tokenisation."""

from __future__ import annotations

import re


C = {
    "key":        "\033[1;36m",
    "string_dq":  "\033[33m",
    "string_sq":  "\033[33m",
    "string_lit": "\033[33m",
    "number":     "\033[1;96m",
    "boolean":    "\033[1;95m",
    "null":       "\033[1;37;41m",
    "comment":    "\033[2;90m",
    "anchor":     "\033[1;94m",
    "alias":      "\033[1;94m",
    "tag":        "\033[1;35m",
    "punct":      "\033[90m",
    "directive":  "\033[2;90m",
    "separator":  "\033[1;90m",
    "trailing":   "\033[1;31m",
    "reset":      "\033[0m",
}

# YAML booleans (case-insensitive per spec)
YAML_BOOLEANS = {
    "true", "false", "yes", "no", "on", "off",
    "True", "False", "Yes", "No", "On", "Off",
    "TRUE", "FALSE", "YES", "NO", "ON", "OFF",
}

# YAML null values
YAML_NULLS = {
    "null", "Null", "NULL", "~",
}


def _colorize_token(match: re.Match, ctx: dict) -> str:
    """Return the coloured string for a single regex match."""
    kind = match.lastgroup
    val = match.group(kind)

    if kind == "directive":
        return C["directive"] + val + C["reset"]

    if kind == "separator":
        return C["separator"] + val + C["reset"]

    if kind == "comment":
        return C["comment"] + val + C["reset"]

    if kind == "tag":
        return C["tag"] + val + C["reset"]

    if kind == "anchor":
        return C["anchor"] + val + C["reset"]

    if kind == "alias":
        return C["alias"] + val + C["reset"]

    if kind == "string_dq":
        return C["string_dq"] + val + C["reset"]

    if kind == "string_sq":
        return C["string_sq"] + val + C["reset"]

    if kind == "number":
        # Check if this is actually a boolean or null value
        stripped = val.strip()
        if stripped in YAML_BOOLEANS:
            return C["boolean"] + val + C["reset"]
        if stripped in YAML_NULLS:
            return C["null"] + val + C["reset"]
        return C["number"] + val + C["reset"]

    if kind == "keyword":
        kw = val.strip()
        if kw in YAML_BOOLEANS:
            return C["boolean"] + val + C["reset"]
        if kw in YAML_NULLS:
            return C["null"] + val + C["reset"]
        return val

    if kind == "key_marker":
        # : at the end of a key or after a key
        return C["punct"] + val + C["reset"]

    if kind in ("dash", "brace_open", "brace_close", "bracket_open", "bracket_close", "colon"):
        return C["punct"] + val + C["reset"]

    # Whitespace and other -- pass through unchanged
    return val


# Token regex for YAML, ordered by priority:
# 1. Directives (%YAML, %TAG)
# 2. Document separators (---, ...)
# 3. Comments (# to end of line)
# 4. Tags (!... or !!...)
# 5. Anchors (&name) and aliases (*name)
# 6. Double-quoted strings
# 7. Single-quoted strings
# 8. Numbers (including booleans/nulls that look like numbers)
# 9. Keywords (true/false/null/yes/no/etc.)
# 10. Punctuation (dash, braces, brackets, colon for keys)
# 11. Whitespace
_TOKEN_RE = re.compile(
    r"""(?P<directive>%[A-Za-z_-]+\s.*)"""                                    # %YAML 1.1
    r'|(?P<separator>---|\.\.\.)'                                              # --- or ...
    r'|(?P<comment>#.*$)'                                                      # comments
    r'|(?P<tag>![Ii]n![^ ]*|!![A-Za-z_-]+|![-;\/!\|,\.a-zA-Z0-9_%]*)'         # tags
    r'|(?P<anchor>&[A-Za-z_-][A-Za-z0-9_-]*)'                                  # anchors &name
    r'|(?P<alias>\*[A-Za-z_-][A-Za-z0-9_-]*)'                                  # aliases *name
    r"""|(?P<string_dq>"(?:[^"\\]|\\.)*")"""                                    # "double quoted"
    r"""|(?P<string_sq>'(?:''|[^'])*')"""                                       # 'single quoted'
    r'|(?P<number>-?(?:0|[1-9][0-9_]*)(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]*)?)\b' # numbers
    r'|(?P<keyword>(?<![A-Za-z0-9_])(?:true|false|null|yes|no|on|off|True|False|Null|Yes|No|On|Off|TRUE|FALSE|NULL|YES|NO|ON|OFF)(?![A-Za-z0-9_]))'  # keywords
    r'|(?P<key_marker>:\s)'                                                    # key separator :
    r'|(?P<dash>-[\s:])'                                                       # list item -
    r'|(?P<brace_open>\{)'                                                     # {
    r'|(?P<brace_close>\})'                                                    # }
    r'|(?P<bracket_open>\[)'                                                   # [
    r'|(?P<bracket_close>\])'                                                  # ]
    r'|(?P<colon>:)'                                                           # :
    r'|(?P<ws>\s+)'                                                            # whitespace
)


class _Ctx:
    """Mutable context shared across line processing."""

    def __init__(self):
        self.flow_depth = 0  # track flow style nesting { } [ ]


def highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-coloured version of YAML text.

    Parameters
    ----------
    source : str
        YAML source text (may be well-formed or malformed).
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

    ctx = _Ctx()

    for line in lines:
        coloured_line = _colorize_line(line, ctx)
        if show_trailing:
            coloured_line = _visualize_trailing(coloured_line, line)
        result_parts.append(coloured_line)

    return "".join(result_parts)


def _colorize_line(line: str, ctx: _Ctx) -> str:
    """Colorize a single YAML line."""
    parts: list[str] = []
    pos = 0

    for m in _TOKEN_RE.finditer(line):
        if m.start() > pos:
            parts.append(line[pos:m.start()])
        parts.append(_colorize_token(m, ctx.__dict__))
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
    """Produce a syntax-highlighted unified diff between two YAML sources.

    Parameters
    ----------
    old_source / new_source : plain-text YAML sources.
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
