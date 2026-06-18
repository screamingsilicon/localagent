from __future__ import annotations

import re
from typing import Any


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

        act = {
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
            find_m = re.search(r'(?m)^[ \t]*<find>\n([\s\S]*?)\n^[ \t]*</find>', inner)
            rep_m = re.search(r'(?m)^[ \t]*<replace>\n([\s\S]*?)\n^[ \t]*</replace>', inner)
            act["find"] = find_m.group(1).strip('\n') if find_m else ""
            act["replace"] = rep_m.group(1).strip('\n') if rep_m else ""

        actions.append(act)

    return actions