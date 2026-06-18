import difflib


C = {
    "diff_add_bg":  "\033[48;5;22m",
    "diff_del_bg":  "\033[48;5;52m",
    "diff_hdr":     "\033[1;90m",
    "diff_add_m":   "\033[1;32m",
    "diff_del_m":   "\033[1;31m",
    "reset":        "\033[0m",
}


def _apply_bg(text: str, bg_code: str) -> str:
    """Wrap text with a background colour, preserving existing resets.

    After every \\033[0m (reset) inside *text*, re-inject the background
    so syntax-highlighted segments don't lose the tint.
    """
    return (
        bg_code
        + text.replace(C["reset"], C["reset"] + bg_code)
        + "\033[0K"
        + C["reset"]
    )


def diff_highlight(
    old_source: str,
    new_source: str,
    old_colored: str | None = None,
    new_colored: str | None = None,
    old_label: str = "old",
    new_label: str = "new",
    context_lines: int = 3,
) -> str:
    """Produce a syntax-highlighted unified diff.

    Parameters
    ----------
    old_source / new_source : plain-text sources (used by difflib for comparison).
    old_colored / new_colored : pre-highlighted versions.  If *None*, the
        plain source is used as-is (plain-text diff mode).
    old_label / new_label : labels shown in the diff header.
    context_lines : number of context lines around changes.

    Returns
    -------
    ANSI-coloured unified diff string.
    """
    old_colored = old_colored or old_source
    new_colored = new_colored or new_source

    old_lines = old_source.splitlines(keepends=True)
    new_lines = new_source.splitlines(keepends=True)
    old_col_lines = old_colored.splitlines(True)
    new_col_lines = new_colored.splitlines(True)

    diff_iter = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=old_label, tofile=new_label,
        n=context_lines, lineterm="",
    )

    out: list[str] = []
    old_idx = 0
    new_idx = 0

    for raw_line in diff_iter:
        line = raw_line.rstrip("\n")
        if not line:
            continue

        if line.startswith("--- ") or line.startswith("+++ "):
            out.append(f"{C['diff_hdr']}{line}{C['reset']}\n")
            continue

        if line.startswith("@@"):
            out.append(f"{C['diff_hdr']}{line}{C['reset']}\n")
            continue

        if line.startswith("+"):
            hl = new_col_lines[new_idx].rstrip("\n") if new_idx < len(new_col_lines) else ""
            out.append(
                f"{C['diff_add_bg']}{C['diff_add_m']}+{C['reset']}"
                f"{_apply_bg(hl, C['diff_add_bg'])}\n"
            )
            new_idx += 1

        elif line.startswith("-"):
            hl = old_col_lines[old_idx].rstrip("\n") if old_idx < len(old_col_lines) else ""
            out.append(
                f"{C['diff_del_bg']}{C['diff_del_m']}-{C['reset']}"
                f"{_apply_bg(hl, C['diff_del_bg'])}\n"
            )
            old_idx += 1

        else:
            content = line[1:] if line and line[0] == " " else line
            hl = new_col_lines[new_idx].rstrip("\n") if new_idx < len(new_col_lines) else content
            out.append(f"{C['diff_hdr']} {C['reset']}{hl}\n")
            old_idx += 1
            new_idx += 1

    return "".join(out)


def plain_diff(
    old_source: str,
    new_source: str,
    old_label: str = "old",
    new_label: str = "new",
    context_lines: int = 3,
) -> str:
    """Convenience wrapper: diff without any pre-highlighting."""
    return diff_highlight(
        old_source, new_source,
        old_colored=None, new_colored=None,
        old_label=old_label, new_label=new_label,
        context_lines=context_lines,
    )


