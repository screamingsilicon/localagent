from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any




class SessionManager:
    """Manages session logging and retrieval."""

    def __init__(self, cwd: str, log_path: str | None = None):
        self.cwd = cwd
        if log_path is not None:
            # User specified a full path for the session log
            self.log_file = Path(log_path)
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_dir_for_listing = self.log_file.parent
        else:
            # Default: ~/.localagent/logs/<cwd_name>/session_<timestamp>.jsonl
            self.log_dir = Path.home() / ".localagent" / "logs" / Path(cwd).name
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.log_file = self.log_dir / f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
            self._log_dir_for_listing = self.log_dir
        self._write_log({"type": "session", "cwd": self.cwd, "started_at": time.time()})

    @property
    def session_file(self) -> Path:
        return self.log_file

    def _write_log(self, rec: dict):
        with open(self.session_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def log_message(self, role: str, content: str):
        self._write_log({"type": "message", "ts": time.time(), "role": role, "content": content})

    def log_tool_call(self, tool: str, success: bool, meta: dict = None):
        m = meta or {}
        self._write_log({"type": "tool", "ts": time.time(), "tool": tool, "success": success, **m})

    def log_event(self, event: str, extra: dict = None):
        """Log a non-message event (e.g. turn_interrupted, compaction)."""
        rec = {"type": "event", "ts": time.time(), "event": event}
        if extra:
            rec.update(extra)
        self._write_log(rec)

    def save(self):
        """Flush and sync session file to disk (for explicit flush points)."""
        fd = self.session_file.open("a")
        try:
            import os as _os
            _os.fsync(fd.fileno())
        finally:
            fd.close()

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions = []
        for p in sorted(self._log_dir_for_listing.glob("*.jsonl"), reverse=True):
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
        """Load messages from a previous session.

        If *session_id* contains a path separator or has a .jsonl extension,
        treat it as an absolute/relative file path.  Otherwise look inside
        the default log directory.
        """
        if "/" in session_id or session_id.endswith(".jsonl"):
            path = Path(session_id)
        else:
            path = self._log_dir_for_listing / f"{session_id}.jsonl"

        if not path.exists():
            raise FileNotFoundError(f"Session {session_id} not found at {path}")

        messages = []
        for line in path.read_text().splitlines():
            if '"type": "message"' in line:
                rec = json.loads(line)
                if rec.get("role") != "system":
                    messages.append(rec)
        return messages

    def load_session_from_path(self, jsonl_path: str) -> list[dict]:
        """Load messages from an arbitrary JSONL file path."""
        path = Path(jsonl_path)
        if not path.exists():
            raise FileNotFoundError(f"Session file not found: {jsonl_path}")
        messages = []
        for line in path.read_text().splitlines():
            if '"type": "message"' in line:
                rec = json.loads(line)
                if rec.get("role") != "system":
                    messages.append(rec)
        return messages