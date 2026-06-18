
"""Markdown -> ANSI terminal renderer for localagent tool blocks and prose.

Standalone -- no dependencies outside the Python standard library.

Usage:
    from libraries.render_markdown import render_md, MD_BLANK

    result = render_md("# Hello **world**")
    if result is not MD_BLANK():
        print(result)
"""

from __future__ import annotations

import difflib
import re
import shutil
import os
import unicodedata

from highlighters import highlight_bash


def _get_diff_highlighter(path: str):
    """Return a diff_highlight function based on file extension, or None."""
    ext = os.path.splitext(path)[1].lower()
    lang_map = {
        ".py": "python",
        ".pyi": "python",
        ".sh": "bash",
        ".bash": "bash",
        ".html": "html",
        ".htm": "html",
    }
    lang = lang_map.get(ext)
    if not lang:
        return None
    try:
        from highlighters import get_highlighter
        _, diff_fn = get_highlighter(lang)
        return diff_fn
    except (KeyError, ImportError):
        return None


def _get_highlighter(path: str):
    """Return a highlight function based on file extension, or None."""
    ext = os.path.splitext(path)[1].lower()
    lang_map = {
        ".py": "python",
        ".pyi": "python",
        ".sh": "bash",
        ".bash": "bash",
        ".html": "html",
        ".htm": "html",
    }
    lang = lang_map.get(ext)
    if not lang:
        return None
    try:
        from highlighters import get_highlighter
        hl_fn, _ = get_highlighter(lang)
        return hl_fn
    except (KeyError, ImportError):
        return None




_CODE_BLOCK_RE = re.compile(
    r"^```([A-Za-z0-9_+-]*)\s*\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


_LANG_ALIASES: dict[str, str] = {
    
    "python": "python", "py": "python", "python3": "python",
    "py3": "python", "cpython": "python",
    
    "bash": "bash", "sh": "bash", "shell": "bash", "zsh": "bash",
    "ksh": "bash", "fish": "bash", "terminal": "bash", "console": "bash",
    "cmd": "bash", "powershell": "bash", "ps1": "bash",
    
    "html": "html", "htm": "html", "xhtml": "html",
    "xml": "html", "svg": "html", "css": "html",
    
    "json": None, "yaml": None, "yml": None,
    "toml": None, "ini": None, "cfg": None,
    "diff": None, "patch": None,
    
    "js": None, "javascript": None, "ts": None, "typescript": None,
    "go": None, "rust": None, "rs": None,
    "java": None, "c": None, "cpp": None, "cc": None, "cxx": None,
    "ruby": None, "rb": None, "php": None,
    "sql": None, "markdown": None, "md": None,
    "latex": None, "tex": None,
    "dockerfile": None, "makefile": None, "cmake": None,
    "proto": None, "graphql": None,
    "log": None, "text": None, "plaintext": None, "none": None,
}

_CODE_BG       = ""
_CODE_LINENO   = "\033[38;5;242m"


def _resolve_lang(lang_tag: str) -> tuple[str | None, str]:
    """Resolve a language tag to (highlighter_name_or_None, display_label).

    Returns the internal highlighter key (or None for plain text) and
    a human-readable label for the header.
    """
    lang_lower = lang_tag.strip().lower() if lang_tag else ""
    highlighter_name = _LANG_ALIASES.get(lang_lower)

    
    DISPLAY_NAMES: dict[str, str] = {
        None: "text",
        "python": "Python",
        "bash": "Bash",
        "html": "HTML",
    }
    display = DISPLAY_NAMES.get(highlighter_name)
    if display is None:
        
        display = lang_tag.strip().title() if lang_tag else "Text"

    return highlighter_name, display


def _get_code_highlighter(highlighter_name: str | None):
    """Get a syntax highlight function for fenced code blocks.

    Returns a callable or None.
    """
    if highlighter_name is None:
        return None
    try:
        from highlighters import get_highlighter
        hl_fn, _ = get_highlighter(highlighter_name)
        return hl_fn
    except (KeyError, ImportError):
        return None


def render_fenced_code_block(text: str) -> str | None:
    """Render a fenced code block (```lang ... ```) to ANSI with syntax highlighting.

    Features:
      - Syntax highlighting via the highlighters module
      - Language header in muted grey italic
      - Falls back gracefully for unknown languages

    Returns rendered string or None if *text* is not a fenced code block.
    """
    m = _CODE_BLOCK_RE.match(text.strip())
    if not m:
        return None

    lang_tag = m.group(1)
    code = m.group(2)

    
    if code.endswith("\n"):
        code = code[:-1]

    highlighter_name, display_label = _resolve_lang(lang_tag)
    hl_fn = _get_code_highlighter(highlighter_name)

    w = shutil.get_terminal_size((80, 20)).columns

    res: list[str] = []

    
    if lang_tag:
        _LANG_HDR = "\033[3;38;5;242m"
        header_text = display_label.lower()
        res.append(f"{_LANG_HDR} {header_text}{_RESET}")

    
    if hl_fn:
        highlighted = hl_fn(code)
        hl_lines = highlighted.split("\n")
    else:
        hl_lines = code.split("\n")

    for line in hl_lines:
        res.append(f"{_CODE_BG}{line}{_CLEAR_LINE}")

    return "\n".join(res)

_MD_BLANK = object()
MD_BLANK = _MD_BLANK


_RESET       = "\033[0m"
_BOLD        = "\033[1m"
_ITALIC      = "\033[3m"
_STRIKE      = "\033[9m"
_CLEAR_LINE  = "\033[K"

_RE_ANSI = re.compile(r"\033\[[0-9;]*m")


def _visible_len(s: str) -> int:
    """Return length of string excluding ANSI escape sequences."""
    return len(_RE_ANSI.sub("", s))


def _pad_to(text: str, width: int) -> str:
    """Pad text with spaces to reach *width* visible characters (accounts for ANSI codes)."""
    needed = width - _visible_len(text)
    if needed > 0:
        return text + " " * needed
    return text

_H1_COLOR    = "\033[1;4;38;5;213m"
_H2_COLOR    = "\033[1;38;5;213m"
_H3_COLOR    = "\033[1;38;5;177m"

_INLINE_CODE_BG = "\033[48;5;238m"
_LIST_BULLET    = "\033[38;5;214m"
_LINK_TEXT      = "\033[38;5;111;4m"
_LINK_URL       = "\033[38;5;240m"

_BG_WRITE_HDR  = "\033[48;5;31m\033[38;5;255m"
_BG_EDIT_HDR   = "\033[48;5;96m\033[38;5;255m"
_BG_SHELL_HDR  = "\033[48;5;239m\033[38;5;255m"
_BG_BODY       = "\033[48;5;236m\033[38;5;252m"
_BG_SHELL_BODY = "\033[48;5;235m\033[38;5;250m"

_DIFF_ADD_BG   = "\033[48;5;22m"
_DIFF_DEL_BG   = "\033[48;5;52m"
_DIFF_CTX_BG   = "\033[48;5;236m"


def _char_display_width(ch: str) -> int:
    """Return the terminal column width for a single character.

    Most CJK ideographs and many emojis render as 2 columns in terminals.
    """
    import unicodedata
    cat = unicodedata.category(ch)
    if cat in ("Lo", "No"):
        return 2
    cp = ord(ch)
    if (0x1F600 <= cp <= 0x1F64F or
        0x1F300 <= cp <= 0x1F5FF or
        0x1F680 <= cp <= 0x1F6FF or
        0x1F900 <= cp <= 0x1F9FF or
        0x2600 <= cp <= 0x26FF or
        0x2700 <= cp <= 0x27BF or
        0xFE00 <= cp <= 0xFE0F or
        0x1FA00 <= cp <= 0x1FA6F or
        0x1FA70 <= cp <= 0x1FAFF):
        return 2
    return 1


def _display_width(s: str) -> int:
    """Return the terminal display width of a string (accounting for wide chars)."""
    return sum(_char_display_width(ch) for ch in s)


def _ansi_display_width(s: str) -> int:
    """Return the terminal display width of a string, excluding ANSI escape sequences.

    Accounts for wide characters (CJK, emojis) that occupy 2 terminal columns.
    """
    return _display_width(_RE_ANSI.sub("", s))


def _dljust(s: str, width: int) -> str:
    """Left-justify *s* to *width* terminal columns."""
    pad = max(0, width - _ansi_display_width(s))
    return s + " " * pad


def _dcenter(s: str, width: int) -> str:
    """Center *s* in *width* terminal columns."""
    total_pad = max(0, width - _ansi_display_width(s))
    left = total_pad // 2
    right = total_pad - left
    return " " * left + s + " " * right


def _drjust(s: str, width: int) -> str:
    """Right-justify *s* to *width* terminal columns."""
    pad = max(0, width - _ansi_display_width(s))
    return " " * pad + s


def _is_md_list_item(line: str) -> bool:
    """Return True if *line* is a markdown unordered list item."""
    return line.startswith("- ") or line.startswith("* ")




_TABLE_LINE_RE = re.compile(r"^\|(.+)\|\s*$")
_TABLE_NO_TRAILING_PIPE_RE = re.compile(r"^([^|][^|]*(?:\|[^|][^|]*)*)\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s\-:|]+\|?\s*$")


def _is_table_line(line: str) -> bool:
    """Return True if *line* looks like a markdown table row (pipe-delimited)."""
    stripped = line.strip()
    if not stripped:
        return False
    
    if _TABLE_LINE_RE.match(stripped):
        return True
    
    if "|" in stripped and _TABLE_NO_TRAILING_PIPE_RE.match(stripped):
        return True
    
    if stripped.startswith("|") and "|" in stripped[1:]:
        return True
    
    if stripped.endswith("|") and "|" in stripped[:-1]:
        return True
    return False


def _is_table_separator(line: str) -> bool:
    """Return True if *line* is a table separator row (e.g. |---|---|)."""
    stripped = line.strip()
    if not stripped:
        return False
    
    has_pipe = "|" in stripped
    
    content = stripped.replace("|", "").replace(" ", "")
    if not content:
        return False
    if all(c in "-:" for c in content) and (has_pipe or len(content) > 0):
        return True
    return False


def _parse_table_row(line: str) -> list[str]:
    r"""Parse a single table row into cells, handling edge cases.

    Handles:
      - Leading/trailing pipes:  | a | b |
      - No trailing pipe:        a | b | c
      - Escaped pipes:           a \| b | c   → ["a | b", "c"]
      - Empty cells:             |||          → ["", "", ""]
    """
    stripped = line.strip()

    
    sentinel = "\x00PIPE\x00"
    escaped = stripped.replace("\\|", sentinel)

    
    
    if escaped.startswith("|"):
        escaped = escaped[1:]
    if len(escaped) > 0 and escaped.endswith("|"):
        escaped = escaped[:-1]

    cells = [c.strip() for c in escaped.split("|")]
    
    cells = [c.replace(sentinel, "|") for c in cells]

    return cells


def _wrap_text_lines(text: str, width: int) -> list[str]:
    """Word-wrap *text* to fit within *width* display columns.

    Preserves ANSI escape sequences. Splits on whitespace only; a single
    run of non-space characters longer than *width* is hard-broken so the
    table never explodes past the column budget.

    Returns a list of (possibly empty) strings, one per output line.
    """
    if not text:
        return [""]

    
    if _ansi_display_width(text) <= width:
        return [text]

    
    
    tokens = re.split(r"(\s+)", text)

    lines: list[str] = []
    current: list[str] = []
    cur_width = 0

    for tok in tokens:
        tw = _ansi_display_width(tok)
        if tok.strip():
            
            if cur_width + tw > width and current:
                
                lines.append("".join(current))
                current = []
                cur_width = 0

            
            while tw > width:
                
                
                cut_at = 0
                dw = 0
                stripped_tok = _RE_ANSI.sub("", tok)
                for ci, ch in enumerate(stripped_tok):
                    cdw = _char_display_width(ch)
                    if dw + cdw > width:
                        break
                    dw += cdw
                    cut_at = ci + 1

                
                
                
                raw_pos = 0
                vis_count = 0
                hard_cut = None
                it = iter(tok)
                while True:
                    ch = next(it, None)
                    if ch is None:
                        break
                    if ch == "\033" and raw_pos + 1 < len(tok):
                        
                        esc = ch
                        for c in it:
                            esc += c
                            if c == "m":
                                break
                        tok_str = _RE_ANSI.sub("", "".join(ch for ch in tok))
                        hard_cut = raw_pos + cut_at  
                        break
                    vis_count += 1
                    raw_pos += 1

                
                
                
                vis_so_far = 0
                safe_chars: list[str] = []
                ansi_buf = ""
                for ch in tok:
                    if ch == "\033":
                        ansi_buf += ch
                        continue
                    if ansi_buf:
                        ansi_buf += ch
                        if ch == "m":
                            safe_chars.append(ansi_buf)
                            ansi_buf = ""
                        continue
                    cdw = _char_display_width(ch)
                    if vis_so_far + cdw > width and safe_chars:
                        break
                    safe_chars.append(ch)
                    vis_so_far += cdw

                prefix = "".join(safe_chars)
                lines.append("".join(current) + prefix if current else prefix)
                current = []
                cur_width = 0

                
                remaining = tok[len(prefix):] if len(prefix) < len(tok) else ""
                
                if remaining.startswith("\033"):
                    remaining = re.sub(r"^\033\[[0-9;]*m?", "", remaining)
                tok = remaining
                tw = _ansi_display_width(tok)
                continue

            current.append(tok)
            cur_width += tw
        else:
            
            
            
            if current and cur_width > 0:
                if cur_width + 1 > width:
                    
                    lines.append("".join(current))
                    current = []
                    cur_width = 0
                    continue
                current.append(" ")
                cur_width += 1

    if current:
        lines.append("".join(current))

    return lines if lines else [""]


def _normalize_row_heights(
    rows: list[list[str]], col_widths: list[int], n_cols: int,
) -> list[list[list[str]]]:
    """Wrap each cell to its column width and equalise line counts per row.

    Returns a new list where each cell is itself a list of line-strings.
    Shorter cells are padded with blank strings so every cell in a row has
    the same number of lines.
    """
    wrapped: list[list[list[str]]] = []
    for row in rows:
        w_cells: list[list[str]] = []
        for i, cell in enumerate(row):
            cw = col_widths[i] if i < len(col_widths) else 30
            lines = _wrap_text_lines(cell, cw)
            w_cells.append(lines)

        
        max_h = max(len(c) for c in w_cells) if w_cells else 1
        for wc in w_cells:
            while len(wc) < max_h:
                wc.append("")
        wrapped.append(w_cells)
    return wrapped


def _parse_table_alignment(sep_line: str) -> list[str]:
    """Parse alignment from separator row. Returns list of 'left'/'center'/'right'."""
    stripped = sep_line.strip()

    
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    parts = [p.strip() for p in stripped.split("|")]
    aligns = []
    for part in parts:
        if not part:
            aligns.append("left")
            continue
        
        if part.startswith(":") and part.endswith(":"):
            aligns.append("center")
        elif part.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    return aligns


def render_table_block(text: str) -> str | None:
    """Render a complete markdown table block to ANSI Unicode-drawn box.

    Returns rendered string or None if text is not a valid table.
    """
    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 2:
        return None

    
    if not _is_table_line(lines[0]) and not "|" in lines[0]:
        return None

    
    sep_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if _is_table_separator(line):
            sep_idx = i
            break
    if sep_idx is None:
        return None

    
    if sep_idx >= len(lines) - 1:
        return None

    
    header_cells = _parse_table_row(lines[0])
    n_cols = len(header_cells)

    
    aligns = _parse_table_alignment(lines[sep_idx])
    while len(aligns) < n_cols:
        aligns.append("left")
    aligns = aligns[:n_cols]

    
    body_rows: list[list[str]] = []
    for line in lines[sep_idx + 1:]:
        if _is_table_separator(line):
            continue  
        if not "|" in line:
            continue  
        cells = _parse_table_row(line)
        while len(cells) < n_cols:
            cells.append("")
        body_rows.append(cells[:n_cols])

    def _strip_inline_md(s: str) -> str:
        """Remove inline markdown formatting chars so width is measured on visible text only."""
        s = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", s)  
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", s)
        s = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", s)
        s = re.sub(r"~~(.+?)~~", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        return s

    
    all_cells = [header_cells] + body_rows
    col_widths = [3] * n_cols
    for row in all_cells:
        for i, cell in enumerate(row):
            if i < n_cols:
                
                col_widths[i] = max(col_widths[i], min(_display_width(_strip_inline_md(cell)), 40))

    
    
    def _make_clean_cells(rows):
        return [[_strip_inline_md(cell) for cell in row] for row in rows]

    all_cells_clean = _make_clean_cells(all_cells)

    
    h = "\u2500"
    v = "\u2502"
    tl = "\u250C"       
    tr = "\u2510"       
    bl = "\u2514"       
    br = "\u2518"       
    t_top = "\u252C"    
    t_bot = "\u2534"    
    ml = "\u251C"       
    mr = "\u2524"       

    PAD = 1

    def _apply_inline(cell: str) -> str:
        """Apply inline markdown formatting (bold, italic, strike, code) to a cell."""
        c = re.sub(r"\*\*\*(.+?)\*\*\*", lambda m: f"{_BOLD}{_ITALIC}{m.group(1)}{_RESET}", cell)
        c = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{_BOLD}{m.group(1)}{_RESET}", c)
        c = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", lambda m: f"{_ITALIC}{m.group(1)}{_RESET}", c)
        c = re.sub(r"(?<!\w)_(.+?)_(?!\w)", lambda m: f"{_ITALIC}{m.group(1)}{_RESET}", c)
        c = re.sub(r"~~(.+?)~~", lambda m: f"{_STRIKE}{m.group(1)}{_RESET}", c)
        c = re.sub(r"`([^`]+)`", lambda m: f"{_INLINE_CODE_BG}{m.group(1)}\033[49m", c)
        return c

    def _fmt_cell(cell: str, width: int, align: str) -> str:
        formatted = _apply_inline(cell)
        if align == "center":
            inner = _dcenter(formatted, width)
        elif align == "right":
            inner = _drjust(formatted, width)
        else:
            inner = _dljust(formatted, width)
        return " " * PAD + inner + " " * PAD

    eff_widths = [cw + 2 * PAD for cw in col_widths]
    h_seg_top = t_top.join(h * ew for ew in eff_widths)
    h_seg_bot = t_bot.join(h * ew for ew in eff_widths)

    
    all_rows = [header_cells] + body_rows
    
    all_clean = [[_strip_inline_md(c) for c in row] for row in all_rows]
    wrapped = _normalize_row_heights(all_clean, col_widths, n_cols)

    
    _re_delims = re.compile(
        r"(?<!\w)(\*\*\*|\*\*|~~|`)(.+?)\1(?!\w)|"
        r"(?<!\w)([*_])(.+?)\2(?!\w)|"
        r"`([^`]+)`",
    )

    def _split_at_same_bounds(orig: str, clean_lines: list[str]) -> list[str]:
        """Split *orig* at the same visual boundaries found in *clean_lines*.

        The wrapping function may discard trailing whitespace when a line is
        full.  Before starting each new segment we skip over such discarded
        whitespace in *orig* so split boundaries stay aligned.
        """
        if not clean_lines:
            return [orig]
        result: list[str] = []
        oi = 0  
        for seg_idx, seg in enumerate(clean_lines):
            tgt = len(seg)
            if tgt == 0:
                result.append("")
                continue

            
            
            
            if seg_idx > 0 and oi < len(orig) and orig[oi].isspace():
                if tgt > 0 and oi + 1 < len(orig) and orig[oi + 1] == seg[0]:
                    oi += 1  

            buf: list[str] = []
            vc = 0  
            while vc < tgt and oi < len(orig):
                m = _re_delims.match(orig, oi)
                if m:
                    inner = m.group(2) or m.group(4) or m.group(6) or ""
                    if not inner:
                        inner = m.group(3) or m.group(5) or ""
                    full = m.group(0)
                    iw = _display_width(inner)
                    if vc + iw <= tgt:
                        buf.append(full)
                        vc += iw
                        oi = m.end()
                    else:
                        break
                else:
                    ch = orig[oi]
                    cp = ord(ch)
                    cat = unicodedata.category(ch)
                    cw = 2 if (cat in ("Lo", "No") or 0x1F600 <= cp <= 0x1F64F
                               or 0x1F300 <= cp <= 0x1F5FF or 0x2600 <= cp <= 0x26FF) else 1
                    buf.append(ch)
                    vc += cw
                    oi += 1
            result.append("".join(buf))
        if oi < len(orig):
            leftover = orig[oi:]
            if leftover:
                if result:
                    result[-1] += leftover
                else:
                    result.append(leftover)
        return result

    re_wrapped: list[list[list[str]]] = []
    for row_orig, row_clean in zip(all_rows, wrapped):
        rw_cells: list[list[str]] = []
        for cell_orig, clines in zip(row_orig, row_clean):
            rw_cells.append(_split_at_same_bounds(cell_orig, clines))
        max_h = max(len(c) for c in rw_cells) if rw_cells else 1
        for wc in rw_cells:
            while len(wc) < max_h:
                wc.append("")
        re_wrapped.append(rw_cells)

    wrapped_header = re_wrapped[0]       
    wrapped_body   = re_wrapped[1:]

    def _fmt_cell_lines(cell_lines: list[str], width: int, align: str) -> list[str]:
        """Return a list of formatted line-strings for one (possibly multi-line) cell."""
        out: list[str] = []
        for cl in cell_lines:
            formatted = _apply_inline(cl)
            if align == "center":
                inner = _dcenter(formatted, width)
            elif align == "right":
                inner = _drjust(formatted, width)
            else:
                inner = _dljust(formatted, width)
            out.append(" " * PAD + inner + " " * PAD)
        return out

    def _join_row_cells(row_cells: list[list[str]], col_widths: list[int],
                        aligns: list[str]) -> list[str]:
        """Join a row of (wrapped) cells into parallel line-strings.

        Returns a list where each element is the full horizontal join for one
        visual line across all columns.
        """
        
        max_lines = max(len(c) for c in row_cells) if row_cells else 0
        joined: list[str] = []
        for li in range(max_lines):
            parts: list[str] = []
            for ci, cell_lines in enumerate(row_cells):
                cw = col_widths[ci] if ci < len(col_widths) else 30
                al = aligns[ci] if ci < len(aligns) else "left"
                cl = cell_lines[li] if li < len(cell_lines) else ""
                parts.extend(_fmt_cell_lines([cl], cw, al))
            joined.append(v.join(parts))
        return joined

    res: list[str] = []
    res.append(tl + h_seg_top + tr)

    
    header_lines = _join_row_cells(wrapped_header, col_widths, aligns)
    for hl in header_lines:
        res.append(f"{v}{_BOLD}{hl}{_RESET}{v}")

    
    res.append(ml + h_seg_top + mr)

    
    for idx, wrow in enumerate(wrapped_body):
        body_lines = _join_row_cells(wrow, col_widths, aligns)
        for bl_line in body_lines:
            res.append(f"{v}{bl_line}{v}")
        
        if idx < len(wrapped_body) - 1:
            res.append(ml + h_seg_top + mr)

    res.append(bl + h_seg_bot + br)
    return "\n".join(res)


def render_md(text: str):
    """Render one or more lines of markdown to ANSI-coloured terminal text.

    Handles:
      - XML tool blocks  <shell>, <edit>, <write>
      - Headers          # / ## / ###
      - Tables           pipe-delimited with separator row
      - Unordered lists  - / *
      - Inline formatting **bold**, *italic*, ~strike~, inline-code, [link](url)

    Returns the rendered string, or the MD_BLANK sentinel for empty input.
    """
    if not text.strip():
        return _MD_BLANK

    w = shutil.get_terminal_size((80, 20)).columns

    
    stripped = text.strip()
    if re.match(r"^[-]{3,}\s*$", stripped) or \
       re.match(r"^\*{3,}\s*$", stripped) or \
       re.match(r"^_{3,}\s*$", stripped):
        return f"\n\033[38;5;242m{'─' * w}{_CLEAR_LINE}{_RESET}"

    m = re.match(
        r'^\s*<(?P<tag>shell|edit|write)'
        r'(?:[^>]*path="(?P<path>[^"]+)")?'
        r'(?:[^>]*remote="(?P<remote>[^"]+)")?'
        r'[^>]*>\n?(?P<inner>[\s\S]*?)\n?</\1>\s*$',
        text,
    )
    if m:
        tag    = m.group("tag")
        path   = m.group("path") or ""
        remote = m.group("remote") or "local"
        inner  = m.group("inner").strip("\r\n")

        res: list[str] = [""]

        if tag == "write":
            header = f" [WRITE] {path} " + (f"({remote})" if remote != "local" else "")
            res.append(f"{_BG_WRITE_HDR}{_BOLD}{header.ljust(w)}{_CLEAR_LINE}{_RESET}")

            hl_fn = _get_highlighter(path)
            if hl_fn is not None:
                highlighted = hl_fn(inner)
                for line in highlighted.split("\n"):
                    res.append(f"{_BG_BODY}  {line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")
            else:
                for line in inner.split("\n"):
                    res.append(f"{_BG_BODY}  {line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")

        elif tag == "edit":
            header = f" [EDIT] {path} " + (f"({remote})" if remote != "local" else "")
            res.append(f"{_BG_EDIT_HDR}{_BOLD}{header.ljust(w)}{_CLEAR_LINE}{_RESET}")

            f_m = re.search(r"<find>\n?([\s\S]*?)\n?</find>", inner)
            r_m = re.search(r"<replace>\n?([\s\S]*?)\n?</replace>", inner)

            if f_m and r_m:
                old_text = f_m.group(1).strip("\r\n")
                new_text = r_m.group(1).strip("\r\n")

                diff_fn = _get_diff_highlighter(path)
                if diff_fn is not None:
                    ctx = min(3, max(1, len(old_text.splitlines()) // 4),
                              max(1, len(new_text.splitlines()) // 4))
                    highlighted = diff_fn(old_text, new_text, old_label=path, new_label=path, context_lines=ctx)
                    for line in highlighted.splitlines():
                        if line.lstrip().startswith(("\033[", "")) and (
                            "---" in line or "+++" in line):
                            continue
                        res.append(f" {line}{_CLEAR_LINE}")
                else:
                    ctx = min(3, max(1, len(old_text.splitlines()) // 4),
                              max(1, len(new_text.splitlines()) // 4))
                    try:
                        from highlighters.differ import plain_diff
                        highlighted = plain_diff(old_text, new_text, old_label=path, new_label=path, context_lines=ctx)
                        for line in highlighted.splitlines():
                            plain = re.sub(r'\033\[[\d;]*m', '', line).strip()
                            if plain.startswith(("--- ", "+++ ")):
                                continue
                            res.append(f" {line}{_CLEAR_LINE}")
                    except ImportError:
                        old_lines = old_text.split("\n")
                        new_lines = new_text.split("\n")
                        ctx2 = min(2, max(0, len(old_lines) // 3), max(0, len(new_lines) // 3))
                        for line in difflib.unified_diff(old_lines, new_lines, n=ctx2, lineterm=""):
                            if line.startswith(("---", "+++")):
                                continue
                            if line.startswith("+"):
                                res.append(f"{_DIFF_ADD_BG} \033[1;32m+\033[39m{line[1:].ljust(w - 3)}{_CLEAR_LINE}{_RESET}")
                            elif line.startswith("-"):
                                res.append(f"{_DIFF_DEL_BG} \033[1;31m-\033[39m{line[1:].ljust(w - 3)}{_CLEAR_LINE}{_RESET}")
                            elif line.startswith("@@"):
                                res.append(f"{_DIFF_CTX_BG} \033[2;38;5;245m{line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")
                            else:
                                content = line[1:] if line and line[0] == " " else line
                                res.append(f"{_DIFF_CTX_BG} \033[38;5;245m {content.ljust(w - 4)}{_CLEAR_LINE}{_RESET}")
            else:
                for line in inner.split("\n"):
                    res.append(f"{_BG_BODY}  {line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")

        elif tag == "shell":
            header = f" [SHELL] {remote} " if remote != "local" else " [SHELL] "
            res.append(f"{_BG_SHELL_HDR}{_BOLD}{header.ljust(w)}{_CLEAR_LINE}{_RESET}")
            highlighted = highlight_bash(inner)
            for line in highlighted.split("\n"):
                res.append(f"{_BG_SHELL_BODY}  $ {_pad_to(line, w - 4)}{_CLEAR_LINE}{_RESET}")

        res.append("")
        return "\n".join(res)

    
    rendered_code = render_fenced_code_block(text)
    if rendered_code is not None:
        return rendered_code

    
    rendered_table = render_table_block(text)
    if rendered_table is not None:
        return rendered_table

    is_header = text.startswith("# ") or text.startswith("## ") or text.startswith("### ")

    if text.startswith("### "):
        t = text[4:]
    elif text.startswith("## "):
        t = text[3:]
    elif text.startswith("# "):
        t = text[2:]
    else:
        t = text

    if is_header:
        header_colors = {"# ": _H1_COLOR, "## ": _H2_COLOR, "### ": _H3_COLOR}
        raw_prefix = text.split(" ")[0] + " "
        base_color = f"{header_colors.get(raw_prefix, _H1_COLOR)}{_BOLD}"
    else:
        base_color = _RESET

    t = re.sub(r"\*\*(.+?)\*\*", lambda m2: f"{_BOLD}{m2.group(1)}{base_color}", t)
    t = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", lambda m2: f"{_ITALIC}{m2.group(1)}{base_color}", t)
    t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", lambda m2: f"{_ITALIC}{m2.group(1)}{base_color}", t)
    t = re.sub(r"~~(.+?)~~", lambda m2: f"{_STRIKE}{m2.group(1)}{base_color}", t)
    t = re.sub(
        r"(?<!\x1b)\[(.+?)\]\((.+?)\)",
        lambda m2: f"{_LINK_TEXT}{m2.group(1)}{_RESET} {_LINK_URL}({m2.group(2)}){base_color}",
        t,
    )
    t = re.sub(r"`([^`]+)`", lambda m2: f"{_INLINE_CODE_BG} {m2.group(1)} \033[49m{base_color}", t)

    if is_header:
        return f"{base_color}{t}{_RESET}"
    elif _is_md_list_item(t):
        return f"{_LIST_BULLET}\u2022{_RESET} {t[2:]}"

    return t





