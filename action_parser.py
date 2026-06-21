from __future__ import annotations

import logging
import re
from typing import Any


_log = logging.getLogger("localagent")


def parse_xml_actions(text: str) -> list[dict[str, Any]]:
    """Parse <shell>, <edit>, and <write> XML action tags from LLM output."""
    actions = []

    pattern = (
        r'(?m)'
        r'<(shell)\b([^>]*)>([\s\S]*?)</\1>|'
        r'^[ \t]*<(edit|write)\b(?=[^>]*\bpath="[^"]+")([^>]*)>\n([\s\S]*?)\n^[ \t]*</\4>'
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

            if not find_matches:
                _log.warning("Malformed edit: missing find tag in %s", act.get("path", "?"))
                continue
            if not rep_matches:
                _log.warning("Malformed edit: missing replace tag in %s", act.get("path", "?"))
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

    return actions