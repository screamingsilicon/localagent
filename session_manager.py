from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


def format_relative_time(ts: float) -> str:
    """Format a timestamp as a relative time string."""
    diff = time.time() - ts
    for unit, limit in [("d", 86400), ("h", 3600), ("m", 60)]:
        if diff >= limit:
            return f"{int(diff // limit)}{unit} ago"
    return "just now"


class SessionManager:
    """Manages session logging and retrieval."""

    def __init__(self, cwd: str):
        self.cwd = cwd
        self.log_dir = Path.home() / ".localagent" / "logs" / Path(cwd).name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.log_dir / f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        self._write_log({"type": "session", "cwd": self.cwd, "started_at": time.time()})

    def _write_log(self, rec: dict):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def log_message(self, role: str, content: str):
        self._write_log({"type": "message", "ts": time.time(), "role": role, "content": content})

    def log_tool_call(self, tool: str, success: bool, meta: dict = None):
        m = meta or {}
        self._write_log({"type": "tool", "ts": time.time(), "tool": tool, "success": success, **m})

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for p in sorted(self.log_dir.glob("*.jsonl"), reverse=True):
            meta = {"id": p.stem, "started_at": p.stat().st_mtime, "last_message_at": p.stat().st_mtime, "messages": 0, "last_user_message": None}
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if not lines:
                    continue
                try:
                    first = json.loads(lines[0])
                    if first.get("type") == "session":
                        meta["started_at"] = first.get("started_at", meta["started_at"])
                except Exception:
                    pass
                for line in lines:
                    if '"type": "message"' in line:
                        meta["messages"] += 1
                        if '"role": "user"' in line:
                            try:
                                meta["last_user_message"] = json.loads(line)
                            except Exception:
                                pass
            sessions.append(meta)
        return sessions

    def load_session(self, session_id: str) -> list[dict]:
        """Load messages from a previous session."""
        path = self.log_dir / f"{session_id}.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"Session {session_id} not found")
        messages = []
        for line in path.read_text().splitlines():
            if '"type": "message"' in line:
                rec = json.loads(line)
                if rec.get("role") != "system":
                    messages.append(rec)
        return messages