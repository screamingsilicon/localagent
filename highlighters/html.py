"""HTML syntax highlighter (with embedded JavaScript support)."""

from __future__ import annotations

import re


C = {
    "tag":        "\033[1;92m",
    "opentag":    "\033[1;92m",
    "closetag":   "\033[1;92m",
    "voidtag":    "\033[1;92m",
    "attr_name":  "\033[1;36m",
    "attr_val":   "\033[33m",
    "doctype":    "\033[1;90m",
    "comment":    "\033[2;90m",
    "entity":     "\033[1;35m",
    "punct":      "\033[90m",
    "text":       "\033[0m",
    "script_tag":    "\033[1;94m",
    "style_tag":     "\033[1;95m",
    "trailing":      "\033[1;31m",
    "js_keyword":    "\033[1;95m",
    "js_string":     "\033[33m",
    "js_comment":    "\033[2;90m",
    "js_number":     "\033[1;35m",
    "js_operator":   "\033[1;37m",
    "js_punct":      "\033[90m",
    "js_template":   "\033[33m",
    "reset":      "\033[0m",
    "fg_reset":   "\033[39m",
}

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

GLOBAL_ATTRS = {
    "accesskey", "autocapitalize", "class", "contenteditable", "dir",
    "draggable", "enterkeyhint", "hidden", "id", "inputmode", "is",
    "itemid", "itemprop", "itemref", "itemscope", "itemtype",
    "lang", "nonce", "popover", "slot", "spellcheck", "style",
    "tabindex", "title", "translate", "dirname",
}

BOOLEAN_ATTRS = {
    "allowfullscreen", "async", "autofocus", "autoplay", "checked",
    "controls", "defer", "disabled", "formnovalidate", "hidden",
    "ismap", "loop", "multiple", "muted", "nomodule", "novalidate",
    "open", "playsinline", "readonly", "required", "reversed",
    "selected",
}

_TOKEN_RE = re.compile(
    r'(?P<comment>!--.*?--)'
    r'|(?P<doctype>!DOCTYPE[^>]*>)'
    r'|(?P<closetag_start></)'
    r'|(?P<opentag_start><)'
    r'|(?P<tag_close>/?>)'
    r'|(?P<string_dq>"[^"]*")'
    r"|(?P<string_sq>'[^']*')"
    r'|(?P<entity>&#[xX][0-9a-fA-F]+;|&#[0-9]+;|[a-zA-Z]+;)'
    r'|(?P<ampersand>&)'
    r'|(?P<eq>=)'
    r'|(?P<tag_name>[a-zA-Z][a-zA-Z0-9-]*)'
    r'|(?P<ws>\s+)'
    r'|(?P<other>.+?)',
    re.DOTALL,
)


class _Ctx:
    def __init__(self):
        self.in_tag = False
        self.tag_name: str | None = None
        self.is_closing = False
        self.in_comment = False
        self.in_doctype = False
        self.in_script = False
        self.in_style = False
        self.raw_depth = 0
        self.prev_token_type: str | None = None
        self.in_js_block_comment = False
        self.js_template_depth = 0


JS_KEYWORDS = {
    "abstract", "as", "async", "await", "break", "case", "catch", "class",
    "const", "continue", "debugger", "default", "delete", "do", "else",
    "enum", "export", "extends", "finally", "for", "from", "function",
    "if", "implements", "import", "in", "instanceof", "interface", "let",
    "new", "of", "package", "private", "protected", "public", "return",
    "static", "super", "switch", "this", "throw", "try", "typeof",
    "var", "void", "while", "with", "yield",
    "true", "false", "null", "undefined", "NaN", "Infinity",
}

_JS_TOKEN_RE = re.compile(
    r"(?P<block_comment>/\*.*?\*/)"
    r"|(?P<line_comment>//[^\n\r]*)"
    r"""|(?P<string_dq>"(?:[^"\\]|\\.)*")"""
    r"""|(?P<string_sq>'(?:[^'\\]|\\.)*')"""
    r"|(?P<string_bt>`)"
    r"|(?P<template_expr>\$\{)"
    r"|(?P<number_hex>0[xX][0-9a-fA-F_]+)"
    r"|(?P<number_bin>0[bB][01_]+)"
    r"|(?P<number_oct>0[oO][0-7_]+)"
    r"|(?P<number>[0-9][0-9_]*\.?[0-9_]*(?:[eE][+-]?[0-9_]+)?)\b"
    r"|(?P<keyword>[a-zA-Z_$][a-zA-Z0-9_$]*)\b"
    r"|(?P<punct>[{}()\[\];,.])"
    r"|(?P<block_open>/\*)"
    r"|(?P<block_close>\*/)"
    r"|(?P<op>=>|[!=]==?|[<>]=?|&&|\|\||[+\-%&|^~?]|\.\.\.)"
    r"|(?P<slash>/)"
    r"|(?P<star>\*)"
    r"|(?P<other>.)",
    re.DOTALL,
)


def _js_color(kind: str) -> str:
    """Return the ANSI colour for a JS token kind."""
    mapping = {
        "keyword":      C["js_keyword"],
        "string_dq":    C["js_string"],
        "string_sq":    C["js_string"],
        "string_bt":    C["js_template"],
        "template_expr":C["js_punct"],
        "line_comment": C["js_comment"],
        "block_comment":C["js_comment"],
        "number_hex":   C["js_number"],
        "number_bin":   C["js_number"],
        "number_oct":   C["js_number"],
        "number":       C["js_number"],
        "op":           C["js_operator"],
        "punct":        C["js_punct"],
    }
    return mapping.get(kind, "")


def _colorize_js_line(line: str, ctx: _Ctx) -> str:
    """Colorize a line of JavaScript source (inside &lt;script&gt;)."""
    parts: list[str] = []

    if ctx.in_js_block_comment:
        end = line.find("*/")
        if end == -1:
            return C["js_comment"] + line + C["fg_reset"]
        parts.append(C["js_comment"] + line[:end + 2] + C["fg_reset"])
        ctx.in_js_block_comment = False
        line = line[end + 2:]

    for m in _JS_TOKEN_RE.finditer(line):
        kind = m.lastgroup
        val = m.group(kind)

        if kind == "keyword":
            if val.lower() in JS_KEYWORDS:
                parts.append(C["js_keyword"] + val + C["fg_reset"])
            else:
                parts.append(val)
        elif kind in ("string_dq", "string_sq"):
            parts.append(_js_color(kind) + val + C["fg_reset"])
        elif kind == "string_bt":
            ctx.js_template_depth += 1
            parts.append(C["js_template"] + "`" + C["fg_reset"])
        elif kind == "template_expr":
            parts.append(C["js_punct"] + "${" + C["fg_reset"])
        elif kind in ("number_hex", "number_bin", "number_oct", "number"):
            parts.append(C["js_number"] + val + C["fg_reset"])
        elif kind == "line_comment":
            parts.append(C["js_comment"] + val + C["fg_reset"])
        elif kind == "block_comment":
            parts.append(C["js_comment"] + val + C["fg_reset"])
        elif kind == "block_open":
            rest = line[m.end():]
            if "*/" not in rest:
                ctx.in_js_block_comment = True
                parts.append(C["js_comment"] + val + rest + C["fg_reset"])
                return "".join(parts)
            else:
                close_idx = rest.index("*/")
                inner = rest[:close_idx]
                parts.append(C["js_comment"] + val + inner + "*/" + C["fg_reset"])
                remaining = rest[close_idx + 2:]
                for m2 in _JS_TOKEN_RE.finditer(remaining):
                    parts.append(_colorize_js_token(m2, ctx))
        elif kind == "block_close":
            parts.append(C["js_comment"] + val + C["fg_reset"])
        elif kind == "op":
            parts.append(C["js_operator"] + val + C["fg_reset"])
        elif kind == "punct":
            if ctx.js_template_depth > 0 and val == "}":
                ctx.js_template_depth = max(0, ctx.js_template_depth - 1)
            parts.append(C["js_punct"] + val + C["fg_reset"])
        else:
            parts.append(val)

    return "".join(parts)


def _colorize_js_token(m, ctx: _Ctx | None = None) -> str:
    """Colorize a single JS token match (used for re-entrant calls)."""
    kind = m.lastgroup
    val = m.group(kind)
    if kind in ("string_dq", "string_sq"):
        return _js_color(kind) + val + C["fg_reset"]
    elif kind == "line_comment":
        return C["js_comment"] + val + C["fg_reset"]
    elif kind in ("number_hex", "number_bin", "number_oct", "number"):
        return C["js_number"] + val + C["fg_reset"]
    elif kind == "op":
        return C["js_operator"] + val + C["fg_reset"]
    elif kind in ("slash", "star"):
        return C["js_operator"] + val + C["fg_reset"]
    elif kind == "punct":
        if ctx and ctx.js_template_depth > 0 and val == "}":
            ctx.js_template_depth = max(0, ctx.js_template_depth - 1)
        return C["js_punct"] + val + C["fg_reset"]
    elif kind == "keyword" and val.lower() in JS_KEYWORDS:
        return C["js_keyword"] + val + C["fg_reset"]
    return val


def _colorize_token(match, ctx: _Ctx):
    """Return the coloured string for a single regex match."""
    kind = match.lastgroup
    val = match.group(kind)

    if kind == "ws":
        return val

    if kind == "comment":
        ctx.in_comment = True
        return C["comment"] + val + C["fg_reset"]

    if kind == "doctype":
        ctx.in_doctype = True
        return C["doctype"] + val + C["fg_reset"]

    if kind == "opentag_start":
        ctx.in_tag = True
        ctx.is_closing = False
        ctx.tag_name = None
        return C["punct"] + "<" + C["fg_reset"]

    if kind == "closetag_start":
        ctx.in_tag = True
        ctx.is_closing = True
        ctx.tag_name = None
        return C["punct"] + "</" + C["fg_reset"]

    if kind == "tag_name":
        if ctx.in_tag and ctx.tag_name is None:
            ctx.tag_name = val.lower()
            if ctx.is_closing:
                return C["closetag"] + val + C["fg_reset"]
            elif ctx.tag_name in VOID_ELEMENTS:
                return C["voidtag"] + val + C["fg_reset"]
            else:
                return C["tag"] + val + C["fg_reset"]
        elif ctx.in_tag and ctx.tag_name is not None:
            return C["attr_name"] + val + C["fg_reset"]
        else:
            return val

    if kind in ("string_dq", "string_sq"):
        if ctx.in_tag:
            return C["attr_val"] + val + C["fg_reset"]
        return val

    if kind == "eq":
        if ctx.in_tag:
            return C["punct"] + "=" + C["fg_reset"]
        return val

    if kind == "tag_close":
        tag_was = ctx.tag_name
        ctx.in_tag = False
        ctx.tag_name = None
        ctx.is_closing = False

        if not ctx.is_closing and tag_was in ("script",):
            ctx.in_script = True
            ctx.raw_depth += 1
        if not ctx.is_closing and tag_was in ("style",):
            ctx.in_style = True
            ctx.raw_depth += 1
        if ctx.is_closing and tag_was == "script":
            ctx.in_script = False
            ctx.in_js_block_comment = False
            ctx.js_template_depth = 0
            ctx.raw_depth = max(0, ctx.raw_depth - 1)
        if ctx.is_closing and tag_was == "style":
            ctx.in_style = False
            ctx.raw_depth = max(0, ctx.raw_depth - 1)

        return C["punct"] + val + C["fg_reset"]

    if kind == "entity":
        return C["entity"] + val + C["fg_reset"]

    if kind == "ampersand":
        return C["entity"] + "&" + C["fg_reset"]

    return val


def highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-coloured version of the HTML source."""
    lines = source.splitlines(True)

    result_parts: list[str] = []
    ctx = _Ctx()

    for lineno, line in enumerate(lines, start=1):
        coloured_line = _colorize_line(line, ctx)
        if show_trailing:
            coloured_line = _visualize_trailing(coloured_line, line)
        result_parts.append(coloured_line)

    full = "".join(result_parts)
    if full.endswith(C["fg_reset"]):
        full = full[:-len(C["fg_reset"])]
    return full


def _colorize_line(line: str, ctx: _Ctx) -> str:
    """Colorize a single HTML line."""
    parts: list[str] = []
    pos = 0

    if ctx.in_script or ctx.in_style:
        close_tag_name = "script" if ctx.in_script else "style"
        pattern = re.compile(
            rf'(?P<close_start></{close_tag_name}>)|(?P<content>[^<]*)',
            re.DOTALL,
        )
        for m in pattern.finditer(line):
            kind = m.lastgroup
            val = m.group(kind)
            if kind == "close_start":
                if close_tag_name == "script":
                    ctx.in_script = False
                    ctx.in_js_block_comment = False
                    ctx.js_template_depth = 0
                else:
                    ctx.in_style = False
                ctx.raw_depth = max(0, ctx.raw_depth - 1)
                parts.append(C["punct"] + "</" + \
                             C["closetag"] + close_tag_name + \
                             C["punct"] + ">" + C["fg_reset"])
            else:
                if ctx.in_script and val:
                    parts.append(_colorize_js_line(val, ctx))
                elif ctx.in_style and val:
                    parts.append(val)
        joined = "".join(parts)
        needs_reset = not joined.endswith(C["fg_reset"]) and \
                      not (joined.endswith("\n") and joined[-len(C["fg_reset"])-1:-1] == C["fg_reset"])
        if joined and needs_reset:
            if joined.endswith("\n"):
                return joined[:-1] + C["fg_reset"] + "\n"
            return joined + C["fg_reset"]
        return joined

    for m in _TOKEN_RE.finditer(line):
        if m.start() > pos:
            parts.append(line[pos:m.start()])
        parts.append(_colorize_token(m, ctx))
        pos = m.end()

    if pos < len(line):
        parts.append(line[pos:])

    joined = "".join(parts)
    needs_reset = not joined.endswith(C["fg_reset"]) and \
                  not (joined.endswith("\n") and joined[-len(C["fg_reset"])-1:-1] == C["fg_reset"])
    if joined and needs_reset:
        if joined.endswith("\n"):
            return joined[:-1] + C["fg_reset"] + "\n"
        return joined + C["fg_reset"]
    return joined


def _visualize_trailing(coloured: str, original_line: str) -> str:
    """Add visual markers for trailing whitespace on a line."""
    stripped = original_line.rstrip()
    trailing = original_line[len(stripped):]
    if not trailing:
        return coloured

    vis = re.sub(r' ', '·', trailing)
    vis = re.sub(r'\t', '→', vis)
    line_end = "\n" if original_line.endswith("\n") else ""
    without_newline = coloured.rstrip("\n")
    return without_newline + C["trailing"] + vis + C["fg_reset"] + line_end


def diff_highlight(
    old_source: str,
    new_source: str,
    old_label: str = "old",
    new_label: str = "new",
    context_lines: int = 3,
) -> str:
    """Produce a syntax-highlighted unified diff between two HTML sources."""
    from .differ import diff_highlight as _raw_diff

    old_colored = highlight(old_source)
    new_colored = highlight(new_source)

    return _raw_diff(
        old_source, new_source,
        old_colored=old_colored, new_colored=new_colored,
        old_label=old_label, new_label=new_label,
        context_lines=context_lines,
    )


