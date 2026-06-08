#!/usr/bin/env python3
"""Markdown -> ANSI terminal renderer for localagent tool blocks and prose.

Standalone -- no dependencies outside the Python standard library.

Usage:
    from libraries.render_markdown import render_md, MD_BLANK

    result = render_md("# Hello **world**")
    if result is not MD_BLANK():
        print(result)
"""

from __future__ import annotations

import re
import shutil

_MD_BLANK = object()  # returned for blank / whitespace-only input
MD_BLANK = _MD_BLANK   # public alias — use `is MD_BLANK` in callers


_RESET       = "\033[0m"
_BOLD        = "\033[1m"
_ITALIC      = "\033[3m"
_STRIKE      = "\033[9m"
_CLEAR_LINE  = "\033[K"

_H1_COLOR    = "\033[1;4;38;5;213m"   # bold + underline, peach
_H2_COLOR    = "\033[1;38;5;213m"    # bold, peach
_H3_COLOR    = "\033[1;38;5;177m"    # bold, light blue

_INLINE_CODE_BG = "\033[48;5;238m"   # dark gray bg
_LIST_BULLET    = "\033[38;5;214m"   # peach bullet
_LINK_TEXT      = "\033[38;5;111;4m"  # cyan + underline
_LINK_URL       = "\033[38;5;240m"   # dim gray

_BG_WRITE_HDR  = "\033[48;5;31m\033[38;5;255m"   # red bg, white fg
_BG_EDIT_HDR   = "\033[48;5;96m\033[38;5;255m"  # teal bg, white fg
_BG_SHELL_HDR  = "\033[48;5;239m\033[38;5;255m" # gray bg, white fg
_BG_BODY       = "\033[48;5;236m\033[38;5;252m" # dark body bg, light text
_BG_SHELL_BODY = "\033[48;5;235m\033[38;5;250m" # shell body: darker + dim


def _char_display_width(ch: str) -> int:
    """Return the terminal column width for a single character.

    Most CJK ideographs and many emojis render as 2 columns in terminals.
    """
    import unicodedata
    cat = unicodedata.category(ch)
    # General categories that are always wide
    if cat in ("Lo", "No"):
        return 2
    # Emoji detection via codepoint ranges (covers most common emoji)
    cp = ord(ch)
    if (0x1F600 <= cp <= 0x1F64F or   # Emoticons
        0x1F300 <= cp <= 0x1F5FF or   # Misc Symbols & Pictographs
        0x1F680 <= cp <= 0x1F6FF or   # Transport & Map
        0x1F900 <= cp <= 0x1F9FF or   # Supplemental Symbols
        0x2600 <= cp <= 0x26FF or     # Misc symbols (includes many emoji)
        0x2700 <= cp <= 0x27BF or     # Dingbats
        0xFE00 <= cp <= 0xFE0F or     # Variation Selectors
        0x1FA00 <= cp <= 0x1FA6F or   # Chess / Misc
        0x1FA70 <= cp <= 0x1FAFF):    # Symbols Extended-A
        return 2
    return 1


def _display_width(s: str) -> int:
    """Return the terminal display width of a string (accounting for wide chars)."""
    return sum(_char_display_width(ch) for ch in s)


def _dljust(s: str, width: int) -> str:
    """Left-justify *s* to *width* terminal columns."""
    pad = max(0, width - _display_width(s))
    return s + " " * pad


def _dcenter(s: str, width: int) -> str:
    """Center *s* in *width* terminal columns."""
    total_pad = max(0, width - _display_width(s))
    left = total_pad // 2
    right = total_pad - left
    return " " * left + s + " " * right


def _drjust(s: str, width: int) -> str:
    """Right-justify *s* to *width* terminal columns."""
    pad = max(0, width - _display_width(s))
    return " " * pad + s


def _is_md_list_item(line: str) -> bool:
    """Return True if *line* is a markdown unordered list item."""
    return line.startswith("- ") or line.startswith("* ")


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
            for line in inner.split("\n"):
                res.append(f"{_BG_BODY}  {line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")

        elif tag == "edit":
            header = f" [EDIT] {path} " + (f"({remote})" if remote != "local" else "")
            res.append(f"{_BG_EDIT_HDR}{_BOLD}{header.ljust(w)}{_CLEAR_LINE}{_RESET}")

            f_m = re.search(r"<find>\n?([\s\S]*?)\n?</find>", inner)
            r_m = re.search(r"<replace>\n?([\s\S]*?)\n?</replace>", inner)

            if f_m and r_m:
                for line in f_m.group(1).strip("\r\n").split("\n"):
                    res.append(f"{_BG_BODY} \033[38;5;196m - {line.ljust(w - 4)}{_CLEAR_LINE}{_RESET}")
                for line in r_m.group(1).strip("\r\n").split("\n"):
                    res.append(f"{_BG_BODY} \033[38;5;46m + {line.ljust(w - 4)}{_CLEAR_LINE}{_RESET}")
            else:
                for line in inner.split("\n"):
                    res.append(f"{_BG_BODY}  {line.ljust(w - 2)}{_CLEAR_LINE}{_RESET}")

        elif tag == "shell":
            header = f" [SHELL] {remote} " if remote != "local" else " [SHELL] "
            res.append(f"{_BG_SHELL_HDR}{_BOLD}{header.ljust(w)}{_CLEAR_LINE}{_RESET}")
            for line in inner.split("\n"):
                res.append(f"{_BG_SHELL_BODY}  $ {line.ljust(w - 4)}{_CLEAR_LINE}{_RESET}")

        res.append("")
        return "\n".join(res)

    _TABLE_RE = re.compile(r"^\|(.+)\|\s*$")

    def _is_table_block(t: str) -> bool:
        lines = [l for l in t.split("\n") if l.strip()]
        if len(lines) < 2:
            return False
        if not _TABLE_RE.match(lines[0]):
            return False
        sep_pattern = re.compile(r"^\|[\s\-:|]+\|\s*$")
        for line in lines[1:]:
            if sep_pattern.match(line):
                return True
        return False

    def _render_table(t: str) -> str:
        raw_lines = [l for l in t.split("\n") if l.strip()]

        def parse_row(line: str) -> list[str]:
            m = _TABLE_RE.match(line)
            if not m:
                return line.strip().split("|")
            return [c.strip() for c in m.group(1).split("|")]

        header_cells = parse_row(raw_lines[0])
        n_cols = len(header_cells)

        aligns: list[str] = ["left"] * n_cols
        for line in raw_lines[1:]:
            m = _TABLE_RE.match(line.strip())
            if not m:
                continue
            sep_inner = m.group(1)
            parts = [p.strip() for p in sep_inner.split("|")]
            for i, part in enumerate(parts):
                if i < n_cols:
                    if part.startswith(":") and part.endswith(":"):
                        aligns[i] = "center"
                    elif part.endswith(":"):
                        aligns[i] = "right"
                    else:
                        aligns[i] = "left"
            break

        body_rows: list[list[str]] = []
        for line in raw_lines[1:]:
            m = _TABLE_RE.match(line.strip())
            if not m:
                continue
            sep_inner = m.group(1) if m else ""
            parts = [p.strip() for p in sep_inner.split("|")]
            if all(c in "-: " for cell in parts for c in cell):
                continue
            cells = [c.strip() for c in m.group(1).split("|") if m]
            while len(cells) < n_cols:
                cells.append("")
            body_rows.append(cells[:n_cols])

        all_cells = [header_cells] + body_rows
        col_widths = [3] * n_cols
        for row in all_cells:
            for i, cell in enumerate(row):
                if i < n_cols:
                    col_widths[i] = max(col_widths[i], min(_display_width(cell), 40))

        h = "\u2500"       # horizontal
        v = "\u2502"       # vertical
        tl = "\u250C"      # top-left corner
        tr = "\u2510"      # top-right corner
        bl = "\u2514"      # bottom-left corner
        br = "\u2518"      # bottom-right corner
        t_top = "\u252C"   # T-top (header-sep junction)
        t_bot = "\u2534"   # T-bottom (body-sep junction)

        PAD = 1

        def _fmt_cell(cell: str, width: int, align: str) -> str:
            if align == "left":
                inner = _dljust(cell, width)
            elif align == "center":
                inner = _dcenter(cell, width)
            else:  # right
                inner = _drjust(cell, width)
            return " " * PAD + inner + " " * PAD

        eff_widths = [cw + 2 * PAD for cw in col_widths]

        h_seg = lambda widths: t_top.join(h * ew for ew in widths)
        h_seg_bot = lambda widths: t_bot.join(h * ew for ew in widths)

        res: list[str] = []

        res.append(tl + h_seg(eff_widths) + tr)

        header_fmt = v.join(
            _fmt_cell(c, w, a) for c, w, a in zip(header_cells, col_widths, aligns)
        )
        res.append(f"{v}{_BOLD}{header_fmt}{_RESET}{v}")

        # Separator line (T-top junctions)
        res.append(tl + h_seg(eff_widths) + tr)

        for row in body_rows:
            row_fmt = v.join(
                _fmt_cell(c, cw, a) for c, cw, a in zip(row, col_widths, aligns)
            )
            res.append(f"{v}{row_fmt}{v}")

        # Bottom border (T-bottom junctions)
        res.append(bl + h_seg_bot(eff_widths) + br)
        return "\n".join(res)

    if _is_table_block(text):
        return _render_table(text)

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

    # Inline formatting -- order matters! Bold before italic to avoid conflicts.
    t = re.sub(r"\*\*(.+?)\*\*", lambda m2: f"{_BOLD}{m2.group(1)}{base_color}", t)
    t = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", lambda m2: f"{_ITALIC}{m2.group(1)}{base_color}", t)
    t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", lambda m2: f"{_ITALIC}{m2.group(1)}{base_color}", t)
    t = re.sub(r"~~(.+?)~~", lambda m2: f"{_STRIKE}{m2.group(1)}{base_color}", t)
    t = re.sub(
        r"\[(.+?)\]\((.+?)\)",
        lambda m2: f"{_LINK_TEXT}{m2.group(1)}{_RESET} {_LINK_URL}({m2.group(2)}){base_color}",
        t,
    )
    t = re.sub(r"`([^`]+)`", lambda m2: f"{_INLINE_CODE_BG} {m2.group(1)} \033[49m{base_color}", t)

    if is_header:
        return f"{base_color}{t}{_RESET}"
    elif _is_md_list_item(t):
        return f"{_LIST_BULLET}\u2022{_RESET} {t[2:]}"

    return t


def _print_with_spacing(rendered, prev_type: str) -> str:
    """Mimic the spacing logic from localagent.py streaming loop."""
    cur_is_header = rendered.startswith(("\033[1;4;", "\033[1;38;5;"))
    cur_is_list = rendered.startswith(_LIST_BULLET)

    if cur_is_header:
        print()  # blank line before header
    elif prev_type in ("header", "blank") and not cur_is_list:
        print()
    elif prev_type == "list" and not cur_is_list:
        print()

    print(rendered, end="\n")

    if cur_is_header:
        return "header"
    elif cur_is_list:
        return "list"
    else:
        return "other"


if __name__ == "__main__":
    w = shutil.get_terminal_size((80, 20)).columns
    print("=" * w)

    samples = [
        "# Top level header",
        "## Second level",
        "### Third level",
        "- list item one",
        "* list item two",
        "Text with **bold**, *italic*, ~strikethrough~",
        "With `inline code` and [a link](https://example.com)",
        "| Feature     | Status  | Priority |\n|:------------|:-------:|---------:|\n| Tables      | ✅ Done |       10 |\n| Headers     | ✅ Done |        5 |\n| Lists       | ✅ Done |        3 |\n| Inline fmt  | ✅ Done |        8 |",
    ]

    prev = "blank"
    for s in samples:
        r = render_md(s)
        if r is not _MD_BLANK and r:
            prev = _print_with_spacing(r, prev)

    # Blank input assertions
    assert render_md("") is _MD_BLANK, "blank should return sentinel"
    assert render_md("   ") is _MD_BLANK, "whitespace-only should return sentinel"

    print(_RESET + "\nAll smoke tests passed.")