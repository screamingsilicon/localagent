"""SQL syntax highlighter using regex-based tokenisation."""

from __future__ import annotations

import re


C = {
    "keyword":    "\033[1;95m",
    "func":       "\033[1;36m",
    "string":     "\033[33m",
    "number":     "\033[1;96m",
    "comment":    "\033[2;90m",
    "identifier": "\033[37m",
    "operator":   "\033[1;90m",
    "bool":       "\033[1;95m",
    "null":       "\033[1;37;41m",
    "punct":      "\033[90m",
    "trailing":   "\033[1;31m",
    "reset":      "\033[0m",
}

# SQL keywords (case-insensitive in practice, we match case-insensitively)
_SQL_KEYWORDS = {
    # DML
    "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "TRUNCATE",
    # DDL
    "CREATE", "ALTER", "DROP", "TABLE", "DATABASE", "INDEX", "VIEW", "SCHEMA",
    "COLUMN", "ADD", "MODIFY", "CHANGE", "RENAME",
    # Constraints & types
    "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CONSTRAINT", "CHECK", "UNIQUE",
    "NOT", "NULL", "DEFAULT", "AUTO_INCREMENT", "SERIAL",
    "INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
    "VARCHAR", "CHAR", "TEXT", "STRING", "BLOB", "CLOB",
    "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL",
    "BOOLEAN", "BOOL", "DATE", "TIME", "DATETIME", "TIMESTAMP",
    "JSON", "UUID", "BYTEA", "SERIAL",
    # Joins
    "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "NATURAL",
    "ON",
    # Clauses
    "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET",
    "UNION", "ALL", "DISTINCT", "AS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "BETWEEN", "LIKE", "IN", "EXISTS", "ANY", "SOME",
    "IS", "AND", "OR", "ASC", "DESC",
    # Transactions
    "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT",
    # Miscellaneous
    "WITH", "RECURSIVE", "RETURNING", "FETCH", "NEXT", "FIRST", "LAST",
    "TOP", "IF", "EXCEPT", "INTERSECT",
}

# SQL built-in functions (common subset)
_SQL_FUNCTIONS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX",
    "COALESCE", "NULLIF", "NVL", "IFNULL",
    "UPPER", "LOWER", "TRIM", "LTRIM", "RTRIM", "SUBSTRING", "SUBSTR",
    "LENGTH", "LEN", "CONCAT", "REPLACE", "POSITION", "LOCATE",
    "ROUND", "CEIL", "CEILING", "FLOOR", "ABS", "MOD", "POWER", "SQRT",
    "NOW", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP",
    "DATE_TRUNC", "EXTRACT", "TO_CHAR", "TO_DATE",
    "CAST", "TYPEOF", "typeof",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD",
    "ARRAY_AGG", "STRING_AGG", "LISTAGG",
}

# All keywords including functions, for matching
_ALL_KEYWORDS = _SQL_KEYWORDS | _SQL_FUNCTIONS


def _build_keyword_alt() -> str:
    """Build a case-insensitive alternation of all SQL keywords."""
    sorted_kw = sorted(_ALL_KEYWORDS, key=len, reverse=True)
    escaped = [re.escape(kw) for kw in sorted_kw]
    return "(?:" + "|".join(escaped) + ")"


_KEYWORD_ALT = _build_keyword_alt()

_TOKEN_RE = re.compile(
    r"(?P<line_comment>--[^\n]*)"
    r"|(?P<block_comment>/\*.*?\*/)"
    r"""|(?P<string_dq>"(?:[^"\\]|\\.)*")"""
    r"""|(?P<string_sq>'(?:[^'\\]|\\.)*')"""
    r"|(?P<number>-?(?:0|[1-9][0-9_]*)(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]*)?)"
    rf"|(?P<keyword>{_KEYWORD_ALT})(?![A-Za-z0-9_])"
    r"|(?P<operator>(?:<>|<=|>=|=|!=|~|!~|&&|\|\||::|#>>|#>))"
    r"|(?P<plus_minus>[+\-])"
    r"|(?P<times_div_mod>[*/%])"
    r"|(?P<punct>[(),.;:])"
    r"|(?P<ws>\s+)",
    re.IGNORECASE,
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
        return C["string"] + val + C["reset"]

    if kind == "number":
        return C["number"] + val + C["reset"]

    if kind == "keyword":
        upper = val.upper()
        if upper in _SQL_FUNCTIONS:
            return C["func"] + val + C["reset"]
        if upper in ("NULL",):
            return C["null"] + val + C["reset"]
        if upper in ("TRUE", "FALSE"):
            return C["bool"] + val + C["reset"]
        return C["keyword"] + val + C["reset"]

    if kind == "operator":
        return C["operator"] + val + C["reset"]

    if kind in ("plus_minus", "times_div_mod"):
        return C["operator"] + val + C["reset"]

    if kind == "punct":
        return C["punct"] + val + C["reset"]

    # Whitespace and other -- pass through unchanged
    return val


def highlight(source: str, show_trailing: bool = False) -> str:
    """Return an ANSI-coloured version of SQL text.

    Parameters
    ----------
    source : str
        SQL source text (may be well-formed or malformed).
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
    """Colorize a single SQL line."""
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
    """Produce a syntax-highlighted unified diff between two SQL sources.

    Parameters
    ----------
    old_source / new_source : plain-text SQL sources.
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
