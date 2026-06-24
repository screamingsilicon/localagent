from __future__ import annotations

import logging
import re
from typing import Any


_log = logging.getLogger("localagent")


def parse_xml_actions(text: str) -> list[dict[str, Any]]:
    """Parse <shell>, <edit>, and <write> XML action tags from LLM output.

    Returns a list of action dicts.  If the response contains an <edit> or
    <write> tag that doesn't have a ``path=`` attribute, a parse-error action
    is emitted so the agent gets specific feedback instead of a generic nudge.
    """
    actions = []

    # Outer tags that *do* match the full pattern (have path= for edit/write)
    pattern = (
        r'(?m)'
        r'<(shell)\b([^>]*)>([\s\S]*?)</\1>|'
        r'^[ \t]*<(edit|write)\b(?=[^>]*\bpath="[^"]+")([^>]*)>\n([\s\S]*?)\n^[ \t]*</\4>'
    )

    # Detect truncated / unclosed <edit> or <write> tags (opening tag present but
    # no matching closing tag).  These won't match the main pattern above and would
    # otherwise fall through to the generic "no actions" nudge.
    _unclosed_edit_write = re.compile(
        r'(?m)^[ \t]*<(edit|write)\b([^>]*?)>',
    )

    for m in re.finditer(pattern, text):
        if m.group(1):
            tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        else:
            tag, attrs, inner = m.group(4), m.group(5), m.group(6)

        path_m = re.search(r'\bpath="([^"]+)"', attrs)
        remote_m = re.search(r'\bremote="([^"]+)"', attrs)
        timeout_m = re.search(r'\btimeout="([^"]+)"', attrs)

        act: dict[str, Any] = {
            "type": tag,
            "remote": remote_m.group(1) if remote_m else None,
            "path": path_m.group(1) if path_m else "",
            "timeout": int(timeout_m.group(1)) if timeout_m else 60,
        }

        if tag == "shell":
            act["command"] = inner.strip()
        elif tag == "write":
            act["content"] = inner.strip()
        elif tag == "edit":
            # Collect ALL <find> and <replace> pairs (multi-edit support)
            _FIND_PAT  = r'(?m)^[ \t]*<find>\n([\s\S]*?)\n^[ \t]*</find>'
            _REPL_PAT  = r'(?m)^[ \t]*<replace>\n([\s\S]*?)\n^[ \t]*</replace>'

            find_matches  = list(re.finditer(_FIND_PAT, inner))
            rep_matches   = list(re.finditer(_REPL_PAT, inner))

            if not find_matches or not rep_matches:
                missing = []
                if not find_matches:
                    missing.append("<find>")
                if not rep_matches:
                    missing.append("<replace>")
                err_msg = f"Malformed edit on {act.get('path', '?')}: missing {', '.join(missing)} block(s)"
                _log.warning(err_msg)
                actions.append({"type": "error", "message": err_msg})
                continue

            # Pair them by interleaving order (find1,replace1, find2,replace2, ...)
            finds   = [m.group(1).strip('\n') for m in find_matches]
            replaces = [m.group(1).strip('\n') for m in rep_matches]

            # If counts differ, warn but use min length
            n_pairs = min(len(finds), len(replaces))
            if len(finds) != len(replaces):
                _log.warning("edit %s: %d find blocks but %d replace blocks – using %d pairs",
                             act.get("path", "?"), len(finds), len(replaces), n_pairs)

            act["finds"]   = finds[:n_pairs]
            act["replaces"] = replaces[:n_pairs]
            # Backward compat: single-edit key still works
            act["find"]    = finds[0]
            act["replace"] = replaces[0]

        actions.append(act)


    # Catch any <edit> or <write> opening tag that the main pattern didn't match.
    # These are malformed (missing path=, missing find/replace, truncated, etc.)
    # and should produce a specific error instead of the generic "no actions" nudge.
    _main_starts = {m.start() for m in re.finditer(pattern, text)}
    already_reported: set[str] = set()
    for om in _unclosed_edit_write.finditer(text):
        tag_name = om.group(1)
        attrs_str = om.group(2)
        # Skip if this was already successfully parsed by the main pattern
        if om.start() in _main_starts:
            continue
        path_m = re.search(r'\bpath="([^"]+)"', attrs_str)
        path_val = path_m.group(1) if path_m else "?"
        key = f"{tag_name}@{om.start()}"
        if key not in already_reported:
            already_reported.add(key)
            close_tag = f"</{tag_name}>"
            if close_tag not in text[om.end():]:
                err_msg = f"Truncated <{tag_name}> tag on {path_val}: missing closing </{tag_name}>"
            else:
                err_msg = f"Malformed <{tag_name}> tag on {path_val}: could not parse (check path= attribute and required inner blocks)"
            _log.warning(err_msg)
            actions.append({"type": "error", "message": err_msg})

    return actions