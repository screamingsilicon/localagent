"""Python syntax highlighter using the stdlib tokenizer."""

from __future__ import annotations

import io
import re
import tokenize
import keyword


C = {
    "keyword":    "\033[1;92m",   # Bold Bright Green – keywords
    "flag":       "\033[36m",     # Cyan              – builtins, comments, decorators
    "op":         "\033[1;35m",   # Bold Magenta      – operators (+, ==, etc.)
    "env":        "\033[94m",     # Bright Blue       – class/type names (uppercase)
    "string":     "\033[33m",     # Yellow            – strings
    "punct":      "\033[90m",     # Dark Gray         – punctuation (, . : ; etc.)
    "number":     "\033[1;96m",   # Bold Cyan         – numbers / literals
    "arg":        "\033[0m",      # Reset / default   – plain identifiers

    "docstring":  "\033[2;33m",   # Dim Yellow        – docstrings
    "magic":      "\033[1;94m",   # Bold Bright Blue  – magic methods (__init__)
    "special":    "\033[36m",     # Cyan              – self / cls params
    "danger":     "\033[1;37;41m",# Bold White on Red – dangerous calls (eval, exec)
    "dunder":     "\033[2;33m",   # Dim Yellow        – dunder attrs (__name__)
    "fexpr":      "\033[93m",     # Bright Yellow     – f-string expressions
    "annotation": "\033[1;94m",   # Bold Bright Blue  – type annotations
    "trailing":   "\033[1;31m",   # Bold Red          – trailing whitespace marker

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
        self.in_annotation = False       # inside a type annotation after ':' or '->'
        self.annotation_depth = 0        # nesting depth inside annotations (for generics)
        self.paren_depth = 0             # overall paren/bracket depth (tracks function sig)
        self.prev_name: str | None = None  # previous NAME token text
        self.prev_op: str | None = None    # previous OP token text
        self.in_fstring_expr = False     # inside an f-string {} expression
        self.just_saw_def_keyword = False  # flag: we just saw 'def' on this line
        self.var_before_colon: str | None = None  # variable name before ':' (for var annotations)
        self.in_fstring_literal = False     # inside an f-string (between FSTRING_START and FSTRING_END)


def _is_docstring(tok_type, tok_string, tokens, idx):
    """Heuristic: is this STRING the first statement in a block?"""
    if tokenize.tok_name.get(tok_type) != "STRING":
        return False
    # A docstring is a string literal that stands alone as the first token
    # after a def/class/@ line (ignoring structural tokens).
    # Look backwards for context.
    for i in range(idx - 1, max(idx - 50, -1), -1):
        t_type, t_str = tokens[i][0], tokens[i][1]
        t_name = tokenize.tok_name.get(t_type, "")
        if t_name in ("NEWLINE", "INDENT", "DEDENT", "NL"):
            continue
        # Skip structural tokens between def/class and docstring
        if t_name == "OP" and t_str in (":", "(", ")", ",", "->", "=", "**"):
            continue
        # Default values in signatures (e.g., threshold: float = 0.5)
        if t_name in ("NUMBER", "STRING"):
            continue
        # Class/function name itself (e.g., DataProcessor after class)
        if t_name == "NAME" and t_str not in ("def", "class", "async"):
            continue
        # If we find def/class/async → likely docstring
        if t_name == "NAME" and t_str in ("def", "class", "async"):
            return True
        if t_name == "OP" and t_str == "@":
            return True
        break  # something else found — not a docstring
    # Module-level docstring (first real token)
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
        # Reset annotation context on newline — annotations don't span lines
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
        # Literal text inside f-string — color as string
        return C["string"] + tok_string + C["reset"]

    if t == "STRING":
        return C["string"] + tok_string + C["reset"]

    if t == "NUMBER":
        return C["number"] + tok_string + C["reset"]

    if t == "COMMENT":
        return C["flag"] + tok_string + C["reset"]

    if t == "OP":
        # Track paren depth for annotation scoping
        if tok_string in ("(", "[", "{"):
            ctx.paren_depth += 1
        elif tok_string in (")", "]", "}"):
            ctx.paren_depth = max(0, ctx.paren_depth - 1)

        # Track annotation context
        if tok_string == ":":
            if ctx.just_saw_def_keyword and ctx.paren_depth <= 1:
                # This is the final ':' ending a def signature
                ctx.in_annotation = False
                ctx.just_saw_def_keyword = False
            elif ctx.paren_depth >= 1 and ctx.just_saw_def_keyword:
                # Inside def params — this starts a type annotation
                ctx.in_annotation = True
                ctx.annotation_depth = 0
            elif (ctx.paren_depth == 0
                  and ctx.prev_name is not None
                  and ctx.prev_name not in KEYWORDS
                  and ctx.prev_op != "."
                  and ctx.var_before_colon is None):
                # Variable annotation: `results: list[float]`
                ctx.in_annotation = True
                ctx.annotation_depth = 0
                ctx.var_before_colon = ctx.prev_name
        elif tok_string == "->":
            if ctx.just_saw_def_keyword and ctx.paren_depth <= 1:
                # Return type annotation after the closing ')' of def params
                ctx.in_annotation = True
                ctx.annotation_depth = 0
        elif tok_string == ",":
            # End parameter annotation (unless nested in generics)
            if ctx.annotation_depth <= 0:
                ctx.in_annotation = False
        elif tok_string == "(":
            pass
        elif tok_string == "=":
            # Default value / assignment — end annotation for this param
            ctx.in_annotation = False
            ctx.var_before_colon = None

        # Track nesting inside generic annotations like dict[str, list[int]]
        if ctx.in_annotation:
            if tok_string in ("[", "("):
                ctx.annotation_depth += 1
            elif tok_string in ("]", ")"):
                ctx.annotation_depth = max(0, ctx.annotation_depth - 1)

        # f-string expression braces — when inside an f-string, {} delimit expressions
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
        # Magic methods: __init__, __str__, etc.
        if tok_string.startswith("__") and tok_string.endswith("__") and len(tok_string) > 4:
            if ctx.prev_op == "def" or ctx.prev_name in ("def",):
                return C["magic"] + tok_string + C["reset"]
            # If preceded by '.', it's an attribute access → dunder
            if ctx.prev_op == ".":
                return C["dunder"] + tok_string + C["reset"]
            # Standalone __name__ etc. → dunder
            return C["dunder"] + tok_string + C["reset"]

        # self / cls special params
        if tok_string in ("self", "cls"):
            return C["special"] + tok_string + C["reset"]

        # Type annotation context — color ALL names as annotations (including builtins)
        if ctx.in_annotation:
            return C["annotation"] + tok_string + C["reset"]

        # Keywords
        if tok_string in KEYWORDS:
            ctx.just_saw_def_keyword = (tok_string == "def")
            return C["keyword"] + tok_string + C["reset"]

        # Builtins (including exceptions) — danger detection via main loop lookahead
        if tok_string in BUILTINS:
            return C["flag"] + tok_string + C["reset"]

        # Class/type names (uppercase first char)
        if tok_string[0].isupper():
            return C["env"] + tok_string + C["reset"]

        # Plain identifier
        return tok_string

    # Fallback
    return tok_string


def highlight(source: str, show_trailing: bool = False) -> str:
    """Take a Python source string and return an ANSI-colored version."""
    lines = source.splitlines(True)

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError as exc:
        # Try to highlight what we can, underline the error line
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
    # Pre-compute byte offsets for every (row, col) position
    lines = source.splitlines(True)
    line_start: list[int] = [0]
    for ln in lines:
        line_start.append(line_start[-1] + len(ln))

    def _pos_to_offset(row: int, col: int) -> int:
        return line_start[row - 1] + col

    ctx = _Ctx()

    # Build per-line segments: (start_off_in_source, end_off_in_source, colored_text)
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
            # Danger detection (lookahead)
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
                # Each fragment gets its own independent color wrap
                if is_docstring:
                    ctext = C["docstring"] + rline + C["reset"]
                elif is_fstring_literal:
                    ctext = C["string"] + rline + C["reset"]
                else:
                    # Non-string multiline — use pre-split colored parts
                    colored_parts = colored_raw.split("\n")
                    ctext = colored_parts[ri] if ri < len(colored_parts) else rline

                # End offset: just before the \n (so the \n is in the gap)
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

        # Track context for next token
        if t_name == "NAME":
            ctx.prev_name = tok_string
        elif t_name == "OP":
            ctx.prev_op = tok_string

    segs.sort(key=lambda s: s[0])
    result_parts: list[str] = []
    prev_off = 0

    for start_off, end_off, colored_text in segs:
        # Gap between previous token end and this token start (original source)
        if start_off > prev_off:
            gap = source[prev_off:start_off]
            if show_trailing and "\n" in gap:
                gap = _visualize_trailing_in_gap(gap)
            result_parts.append(gap)
        result_parts.append(colored_text)
        prev_off = end_off

    # Handle trailing source after last segment — this is where trailing
    # whitespace on each line lives (spaces/tabs after the last token)
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
    from differ import diff_highlight as _raw_diff

    old_colored = highlight(old_source)
    new_colored = highlight(new_source)

    return _raw_diff(
        old_source, new_source,
        old_colored=old_colored, new_colored=new_colored,
        old_label=old_label, new_label=new_label,
        context_lines=context_lines,
    )


if __name__ == "__main__":
    import sys

    show_trailing = "--trailing" in sys.argv
    if show_trailing:
        sys.argv.remove("--trailing")

    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            src = f.read()
    else:
        src = sys.stdin.read()

    sys.stdout.write(highlight(src, show_trailing=show_trailing))