"""Python syntax highlighter using the stdlib tokenizer."""

from __future__ import annotations

import io
import re
import tokenize
import keyword


C = {
    "keyword":    "\033[1;92m",
    "flag":       "\033[36m",
    "op":         "\033[1;35m",
    "env":        "\033[94m",
    "string":     "\033[33m",
    "punct":      "\033[90m",
    "number":     "\033[1;96m",
    "arg":        "\033[0m",

    "docstring":  "\033[2;33m",
    "magic":      "\033[1;94m",
    "special":    "\033[36m",
    "danger":     "\033[1;37;41m",
    "dunder":     "\033[2;33m",
    "fexpr":      "\033[93m",
    "annotation": "\033[1;94m",
    "trailing":   "\033[1;31m",

    "reset":      "\033[0m"
}

KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}

BUILTINS = {
    "print", "len", "range", "int", "str", "float", "bool", "list", "dict",
    "set", "tuple", "type", "isinstance", "issubclass", "hasattr",
    "getattr", "setattr", "delattr", "callable", "iter", "next", "map",
    "filter", "zip", "enumerate", "reversed", "sorted", "min", "max",
    "sum", "abs", "round", "pow", "divmod", "hash", "id", "repr",
    "input", "open", "super", "property", "staticmethod", "classmethod",
    "format", "vars", "dir", "help", "exec", "eval", "compile",
    "breakpoint", "memoryview", "bytearray", "bytes",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "ImportError", "FileNotFoundError", "RuntimeError",
    "StopIteration", "NotImplementedError", "OverflowError",
}

DANGEROUS = {"eval", "exec", "compile"}

PUNCTUATION = set(",.;()[]{}/@->...")


class _Ctx:
    """Mutable context shared across the token-walk to track state."""

    def __init__(self):
        self.in_annotation = False
        self.annotation_depth = 0
        self.paren_depth = 0
        self.prev_name: str | None = None
        self.prev_op: str | None = None
        self.in_fstring_expr = False
        self.just_saw_def_keyword = False
        self.var_before_colon: str | None = None
        self.in_fstring_literal = False


def _is_docstring(tok_type, tok_string, tokens, idx):
    """Heuristic: is this STRING the first statement in a block?"""
    if tokenize.tok_name.get(tok_type) != "STRING":
        return False
    for i in range(idx - 1, max(idx - 50, -1), -1):
        t_type, t_str = tokens[i][0], tokens[i][1]
        t_name = tokenize.tok_name.get(t_type, "")
        if t_name in ("NEWLINE", "INDENT", "DEDENT", "NL"):
            continue
        if t_name == "OP" and t_str in (":", "(", ")", ",", "->", "=", "**"):
            continue
        if t_name in ("NUMBER", "STRING"):
            continue
        if t_name == "NAME" and t_str not in ("def", "class", "async"):
            continue
        if t_name == "NAME" and t_str in ("def", "class", "async"):
            return True
        if t_name == "OP" and t_str == "@":
            return True
        break
    if idx <= 2:
        for i in range(idx):
            t_name = tokenize.tok_name.get(tokens[i][0], "")
            if t_name not in ("ENCODING", "INDENT", "NEWLINE", "NL", "COMMENT"):
                break
        else:
            return True
    return False


def _colorize_single(tok_type, tok_string, ctx: _Ctx):
    """Return (colored_text,) for a single token."""
    t = tokenize.tok_name.get(tok_type, "")

    if t in ("NEWLINE", "INDENT", "DEDENT", "NL", "ENCODING"):
        ctx.in_annotation = False
        ctx.annotation_depth = 0
        ctx.var_before_colon = None
        return tok_string

    if t == "ENDMARKER":
        return ""

    if t == "FSTRING_START":
        ctx.in_fstring_literal = True
        return C["string"] + tok_string + C["reset"]

    if t == "FSTRING_END":
        ctx.in_fstring_literal = False
        return C["string"] + tok_string + C["reset"]

    if t == "FSTRING_MIDDLE":
        return C["string"] + tok_string + C["reset"]

    if t == "STRING":
        return C["string"] + tok_string + C["reset"]

    if t == "NUMBER":
        return C["number"] + tok_string + C["reset"]

    if t == "COMMENT":
        return C["flag"] + tok_string + C["reset"]

    if t == "OP":
        if tok_string in ("(", "[", "{"):
            ctx.paren_depth += 1
        elif tok_string in (")", "]", "}"):
            ctx.paren_depth = max(0, ctx.paren_depth - 1)

        if tok_string == ":":
            if ctx.just_saw_def_keyword and ctx.paren_depth <= 1:
                ctx.in_annotation = False
                ctx.just_saw_def_keyword = False
            elif ctx.paren_depth >= 1 and ctx.just_saw_def_keyword:
                ctx.in_annotation = True
                ctx.annotation_depth = 0
            elif (ctx.paren_depth == 0
                  and ctx.prev_name is not None
                  and ctx.prev_name not in KEYWORDS
                  and ctx.prev_op != "."
                  and ctx.var_before_colon is None):
                ctx.in_annotation = True
                ctx.annotation_depth = 0
                ctx.var_before_colon = ctx.prev_name
        elif tok_string == "->":
            if ctx.just_saw_def_keyword and ctx.paren_depth <= 1:
                ctx.in_annotation = True
                ctx.annotation_depth = 0
        elif tok_string == ",":
            if ctx.annotation_depth <= 0:
                ctx.in_annotation = False
        elif tok_string == "(":
            pass
        elif tok_string == "=":
            ctx.in_annotation = False
            ctx.var_before_colon = None

        if ctx.in_annotation:
            if tok_string in ("[", "("):
                ctx.annotation_depth += 1
            elif tok_string in ("]", ")"):
                ctx.annotation_depth = max(0, ctx.annotation_depth - 1)

        if tok_string == "{":
            if ctx.in_fstring_literal:
                ctx.in_fstring_expr = True
        elif tok_string == "}":
            if ctx.in_fstring_literal:
                ctx.in_fstring_expr = False

        if tok_string in PUNCTUATION:
            return C["punct"] + tok_string + C["reset"]
        return C["op"] + tok_string + C["reset"]

    if t == "NAME":
        if tok_string.startswith("__") and tok_string.endswith("__") and len(tok_string) > 4:
            if ctx.prev_op == "def" or ctx.prev_name in ("def",):
                return C["magic"] + tok_string + C["reset"]
            if ctx.prev_op == ".":
                return C["dunder"] + tok_string + C["reset"]
            return C["dunder"] + tok_string + C["reset"]

        if tok_string in ("self", "cls"):
            return C["special"] + tok_string + C["reset"]

        if ctx.in_annotation:
            return C["annotation"] + tok_string + C["reset"]

        if tok_string in KEYWORDS:
            ctx.just_saw_def_keyword = (tok_string == "def")
            return C["keyword"] + tok_string + C["reset"]

        if tok_string in BUILTINS:
            return C["flag"] + tok_string + C["reset"]

        if tok_string[0].isupper():
            return C["env"] + tok_string + C["reset"]

        return tok_string

    return tok_string


def highlight(source: str, show_trailing: bool = False) -> str:
    """Take a Python source string and return an ANSI-colored version."""
    lines = source.splitlines(True)

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError as exc:
        err_line = exc.args[0][0] if exc.args and len(exc.args[0]) >= 2 else "?"
        partial_highlight = _highlight_tokens(source, tokens if 'tokens' in dir() else [])
        marker_line = f"{C['danger']}{'!' * max(3, len(str(err_line)))}{C['reset']} {exc}"
        result_lines = partial_highlight.splitlines(True)
        if isinstance(err_line, int) and 0 < err_line <= len(result_lines):
            result_lines[err_line - 1] = C["danger"] + result_lines[err_line - 1] + C["reset"]
        return "".join(result_lines) + marker_line + "\n"

    return _highlight_tokens(source, tokens, show_trailing=show_trailing)


def _highlight_tokens(source: str, tokens: list, show_trailing: bool = False) -> str:
    """Rebuild source from tokens with colors applied.

    Strategy: split every token into per-line fragments so each segment
    covers exactly one line of the original source.  Then merge in order
    filling gaps with original text.
    """
    lines = source.splitlines(True)
    line_start: list[int] = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    def _pos_to_offset(row: int, col: int) -> int:
        return line_start[row - 1] + col

    ctx = _Ctx()

    segs: list[tuple[int, int, str]] = []

    for global_idx, tok in enumerate(tokens):
        tok_type = tok.type
        tok_string = tok.string
        t_name = tokenize.tok_name.get(tok_type, "")

        if t_name in ("NEWLINE", "INDENT", "DEDENT", "NL", "ENCODING", "ENDMARKER"):
            if t_name in ("NEWLINE", "NL"):
                ctx.in_annotation = False
                ctx.annotation_depth = 0
                ctx.var_before_colon = None
            continue

        is_docstring = (t_name == "STRING" and _is_docstring(tok_type, tok_string, tokens, global_idx))
        is_fstring_literal = t_name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END")

        if is_docstring:
            colored_raw = C["docstring"] + tok_string + C["reset"]
        elif is_fstring_literal:
            colored_raw = C["string"] + tok_string + C["reset"]
        else:
            is_dangerous = False
            if t_name == "NAME" and tok_string in DANGEROUS:
                remaining = tokens[global_idx + 1:]
                for future_tok in remaining:
                    ft_name = tokenize.tok_name.get(future_tok.type, "")
                    if ft_name in ("NEWLINE", "INDENT", "DEDENT", "NL"):
                        break
                    if ft_name == "OP" and future_tok.string == "(":
                        is_dangerous = True
                    break

            colored_raw = _colorize_single(tok_type, tok_string, ctx)
            if is_dangerous:
                colored_raw = C["danger"] + tok_string + C["reset"]

        start_row, start_col = tok.start
        end_row, end_col = tok.end

        if "\n" in tok_string:
            raw_lines = tok_string.split("\n")
            cur_row = start_row
            for ri, rline in enumerate(raw_lines):
                off = line_start[cur_row - 1] + (start_col if ri == 0 else 0)
                if is_docstring:
                    ctext = C["docstring"] + rline + C["reset"]
                elif is_fstring_literal:
                    ctext = C["string"] + rline + C["reset"]
                else:
                    colored_parts = colored_raw.split("\n")
                    ctext = colored_parts[ri] if ri < len(colored_parts) else rline

                if ri < len(raw_lines) - 1:
                    eoff = line_start[cur_row] - 1
                else:
                    eoff = line_start[end_row - 1] + end_col

                segs.append((off, eoff, ctext))
                cur_row += 1
        else:
            off = _pos_to_offset(start_row, start_col)
            eoff = _pos_to_offset(end_row, end_col)
            segs.append((off, eoff, colored_raw))

        if t_name == "NAME":
            ctx.prev_name = tok_string
        elif t_name == "OP":
            ctx.prev_op = tok_string

    segs.sort(key=lambda s: s[0])
    result_parts: list[str] = []
    prev_off = 0

    for start_off, end_off, colored_text in segs:
        if start_off > prev_off:
            gap = source[prev_off:start_off]
            if show_trailing and "\n" in gap:
                gap = _visualize_trailing_in_gap(gap)
            result_parts.append(gap)
        result_parts.append(colored_text)
        prev_off = end_off

    if prev_off < len(source):
        tail = source[prev_off:]
        if show_trailing:
            tail = _visualize_trailing_in_gap(tail)
        result_parts.append(tail)

    return "".join(result_parts)


def _visualize_trailing_in_gap(text: str) -> str:
    """Visualize trailing whitespace within a gap chunk.

    Gaps between tokens can span multiple lines (e.g. \\n + indentation).
    Only the FIRST line of such a gap can have trailing whitespace
    (the rest are leading whitespace on subsequent lines).
    For single-line gaps (no \\n), visualize trailing whitespace normally.
    """
    if "\n" in text:
        parts = text.split("\n", 1)
        first_line = parts[0]
        stripped = first_line.rstrip()
        trailing = first_line[len(stripped):]
        if trailing:
            vis = re.sub(r' ', '·', trailing)
            vis = re.sub(r'\t', '→', vis)
            parts[0] = stripped + C["trailing"] + vis + C["reset"]
        return "\n".join(parts)
    else:
        stripped = text.rstrip()
        trailing = text[len(stripped):]
        if trailing:
            vis = re.sub(r' ', '·', trailing)
            vis = re.sub(r'\t', '→', vis)
            return stripped + C["trailing"] + vis + C["reset"]
        return text


def diff_highlight(old_source: str, new_source: str,
                   old_label: str = "old", new_label: str = "new",
                   context_lines: int = 3) -> str:
    """Produce a syntax-highlighted unified diff between two Python sources.

    Highlights both sources in full first, then delegates to the generic
    differ module for background-tinted diff output.
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


