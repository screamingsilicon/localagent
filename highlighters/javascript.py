"""JavaScript syntax highlighter using regex-based tokenisation."""

from __future__ import annotations

import re


C = {
    "keyword":    "\033[1;95m",
    "func":       "\033[1;36m",
    "string_dq":  "\033[33m",
    "string_sq":  "\033[33m",
    "string_tpl": "\033[33m",
    "number":     "\033[1;96m",
    "comment":    "\033[2;90m",
    "operator":   "\033[1;90m",
    "punct":      "\033[90m",
    "trailing":   "\033[1;31m",
    "reset":      "\033[0m",
}

# JavaScript keywords
_JS_KEYWORDS = {
    # Strict mode reserved words
    "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally",
    "for", "function", "if", "import", "in", "instanceof", "let", "new",
    "return", "super", "switch", "this", "throw", "try", "typeof",
    "var", "void", "while", "with", "yield",
    # Contextual keywords
    "async", "await", "from", "of", "static", "get", "set",
    "implements", "interface", "package", "private", "protected", "public",
    "as", "namespace", "declare", "require",
    # Literals
    "true", "false", "null", "undefined", "NaN", "Infinity",
}

# Common built-in functions / constructors
_JS_BUILTINS = {
    # Globals
    "console", "log", "warn", "error", "info", "debug", "table", "time",
    "timeEnd", "trace", "assert", "clear", "dir", "dirxml", "profile",
    "monitorEvents", "unmonitorEvents", "count", "countReset",
    # Built-in functions
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURI",
    "decodeURI", "encodeURIComponent", "decodeURIComponent",
    "eval", "unescape", "escape",
    # DOM / Node.js
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "requestAnimationFrame", "fetch", "XMLHttpRequest",
    "process", "Buffer", "require", "module", "exports", "__dirname",
    "__filename", "globalThis", "global",
    # Constructors
    "Array", "Object", "String", "Number", "Boolean", "Date", "RegExp",
    "Map", "Set", "WeakMap", "WeakSet", "Promise", "Symbol", "Error",
    "TypeError", "ReferenceError", "SyntaxError", "RangeError",
    "URIError", "EvalError",
    # Methods
    "push", "pop", "shift", "unshift", "splice", "slice", "concat",
    "join", "split", "replace", "match", "search", "test", "exec",
    "map", "filter", "reduce", "forEach", "some", "every", "find",
    "findIndex", "includes", "indexOf", "lastIndexOf", "flat", "flatMap",
    "keys", "values", "entries", "has", "get", "set", "delete", "clear",
    "then", "catch", "finally", "all", "race", "resolve", "reject",
}

# All keywords for matching (sorted longest-first)
_ALL_KEYWORDS = sorted(_JS_KEYWORDS | _JS_BUILTINS, key=len, reverse=True)
_KEYWORD_ALT = "|".join(re.escape(kw) for kw in _ALL_KEYWORDS)


_TOKEN_RE = re.compile(
    r"(?P<line_comment>//[^\n]*)"                                          # // comment
    r"|(?P<block_comment>/\*[\s\S]*?\*/)"                                  # /* block */
    r"""|(?P<string_dq>"(?:[^"\\]|\\.)*")"""                                # "double quoted"
    r"""|(?P<string_sq>'(?:[^'\\]|\\.)*')"""                                # 'single quoted'
    r"|(?P<number_hex>0[xX][0-9a-fA-F_]+)"                                 # hex 0xFF
    r"|(?P<number_bin>0[bB][01_]+)"                                        # binary 0b1010
    r"|(?P<number_oct>0[oO][0-7_]+)"                                       # octal 0o755
    r"|(?P<number_dec>-?(?:0|[1-9][0-9_]*)(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]*)?)"  # decimal
    rf"|(?P<keyword>{_KEYWORD_ALT})(?![A-Za-z0-9_$])"                       # keywords
    r"|(?P<operator>(?:"                                                    # operators (multi-char first)
    r"=>|===|!==|&&|\|\||\.\.\.|\?\?"                                      # arrows, equality, logical, spread, nullish
    r"|<<=|>>=|>>>="                                                       # bitwise shift assignment
    r"|<<|>>>|>>"                                                          # bitwise shifts
    r"|<=|>=|==|!="                                                        # comparison
    r"|~=|::"                                                              # tilde-equals, namespaced
    r"|&=|\|=|\^="                                                         # bitwise assignment
    r"|[\+\-\*\/%]=?"                                                      # compound assign: += -= *= /= %= or bare + - * / %
    r"|[\+\-\*\/%=<>!&\|^~?:]))"                                           # single-char operators
    r"|(?P<punct>[{}()\[\];,.])"                                           # punctuation
    r"|(?P<ws>\s+)"                                                        # whitespace
)


def _colorize_token(match: re.Match) -> str:
    """Return the coloured string for a single regex match."""
    kind = match.lastgroup
    val = match.group(kind)

    if kind == "line_comment":
        return C["comment"] + val + C["reset"]

    if kind == "block_comment":
        return C["comment"] + val + C["reset"]

    if kind in ("string_dq", "string_sq"):
        return C["string_dq"] + val + C["reset"]

    if kind == "template":
        return C["string_tpl"] + val + C["reset"]

    if kind in ("number_hex", "number_bin", "number_oct", "number_dec"):
        return C["number"] + val + C["reset"]

    if kind == "keyword":
        upper = val.upper()
        # null/undefined/NaN/Infinity get special treatment (white on red)
        if upper in ("NULL", "UNDEFINED", "NAN", "INFINITY"):
            return "\033[1;37;41m" + val + C["reset"]
        if upper in ("TRUE", "FALSE"):
            return "\033[1;95m" + val + C["reset"]  # boolean: magenta
        if val in _JS_BUILTINS:
            return C["func"] + val + C["reset"]  # built-in function/constructor
        return C["keyword"] + val + C["reset"]

    if kind == "operator":
        return C["operator"] + val + C["reset"]

    if kind == "punct":
        return C["punct"] + val + C["reset"]

    # Whitespace and other -- pass through unchanged
    return val


def highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-coloured version of JavaScript text.

    Parameters
    ----------
    source : str
        JavaScript source text (may be well-formed or malformed).
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
    """Colorize a single JavaScript line."""
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

    vis = re.sub(r" ", "\u00b7", trailing)
    vis = re.sub(r"\t", "\u2192", vis)
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
    """Produce a syntax-highlighted unified diff between two JS sources.

    Parameters
    ----------
    old_source / new_source : plain-text JavaScript sources.
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
