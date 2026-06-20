# localagent — Project Review & Improvement Plan

## Summary

This is a well-architected terminal-based AI agent (~35 files, ~10k LOC) that orchestrates LLM interactions with shell execution, file editing, and writing via XML action tags. The core loop in `localagent.py` is clean, the token estimation in `token_counter.py` is impressively detailed (pure-Python cl100k_base approximation), and the fuzzy matching in `file_ops.py` handles real-world text normalization well.

Below are issues organized by severity, with concrete fixes.

---

## 🔴 P0 — Bugs / Data Loss

### 1. `terminal.py` is completely corrupted (every line duplicated)

Every line in this file appears twice due to what looks like a merge/edit artifact. The file doesn't even compile:
```
IndentationError: expected an indented block after function definition on line 55
```

**Impact:** While no module currently imports from `terminal.py` (the project uses `display.py` instead), this is dead code that could cause confusion or be accidentally imported later.

**Fix:** Either delete it entirely, or fix the duplication and unify with `display.py`. The contents are nearly identical to `display.py` + parts of `shell_executor.py`, suggesting it was an earlier iteration that got corrupted during refactoring.

---

### 2. No session save on clean exit (already in TODO.md P0#1)

Sessions are preserved on `Ctrl+C` but if the agent finishes via `<done/>`, turn timeout, or crash/SIGKILL, there's no explicit flush. The JSONL file is append-mode so individual records survive, but the final state may be incomplete.

**Fix:** Wrap `run_agent_turn` in try/finally:
```python
def run_agent_turn(self, req: str):
    try:
        # ... existing loop ...
    finally:
        self._session_mgr.save()  # persist on any exit path
```

---

### 3. SSH path injection in `file_ops.read_file` / `write_file`

```python
# read_file — line ~250
p = subprocess.run(
    f"ssh {remote} \"cat '{path}'\"",   # ← path with quotes breaks on single-quote paths
    shell=True, capture_output=True, text=True,
)
```

If `path` contains a single quote (e.g., `it's.py`), the command fails or becomes injectable.

**Fix:** Use base64 encoding (same pattern already used in `shell_executor.execute_shell`):
```python
import base64
encoded = base64.b64encode(path.encode()).decode()
cmd = f"ssh {remote} \"echo {encoded} | base64 -d | xargs -0 cat\""
```

---

### 4. `docker_sandbox.docker_exec` has no timeout / watchdog

Unlike `shell_executor.stream_command_output` which has a watchdog thread with configurable timeout, `docker_exec` blocks indefinitely on hung commands.

**Fix:** Add the same watchdog pattern:
```python
def docker_exec(cmd: str, cwd: Optional[str] = None, timeout: int = 60) -> Tuple[list[str], int]:
    # ... add threading watchdog like stream_command_output ...
```

---

## 🟡 P1 — Correctness & Reliability

### 5. `pending_notes` has no public setter (already in TODO.md P1#4)

The list is cleared in `run_agent_turn` but only populated from the REPL `!cmd` feature. No way for external code or hooks to inject context.

**Fix:** Add a public accessor:
```python
def add_note(self, note: str):
    """Queue extra context for the next agent turn."""
    self.pending_notes.append(note)
```

---

### 6. Magic numbers everywhere (already in TODO.md P2#6)

| Value | Location | Meaning |
|-------|----------|---------|
| `50` | `run_agent_turn` max iterations | Max LLM retries per turn |
| `600` | `TURN_TIMEOUT` | Turn timeout in seconds |
| `0.92` | `_ensure_context_fits` | Force-compact threshold |
| `0.65` | `_maybe_compress_context` | Soft-compact threshold |
| `3` | `max_nudges` | Max no-action retries |
| `1100` | `compress_context` | Truncation char limit |
| `300`, `800` | `compress_context` | Keep head/tail chars |

**Fix:** Extract to module-level constants with docstrings, or better yet, move to `_Config`:
```python
_TURN_TIMEOUT              = 600   # seconds
_MAX_ITERATIONS            = 50
_CONTEXT_OVERFLOW_RATIO    = 0.92
_CONTEXT_COMPRESS_RATIO    = 0.65
_MAX_NO_ACTION_NUDGES      = 3
_ACTION_RESULT_HEAD_CHARS  = 300
_ACTION_RESULT_TAIL_CHARS  = 800
```

---

### 7. `docker_sandbox` global mutation in `system_summary()` (already in TODO.md P2#7)

Using `global docker_sandbox` inside a function is fragile and non-reentrant. Both `_run_in_container` and `system_summary` reference the module-level `docker_sandbox`.

**Fix:** Lazy-load once behind a module-level sentinel:
```python
_docker_sandbox_module = None

def _get_docker_sandbox():
    global _docker_sandbox_module
    if _docker_sandbox_module is None:
        try:
            import docker_sandbox as ds
            _docker_sandbox_module = ds
        except ImportError:
            return None
    return _docker_sandbox_module
```

---

### 8. `execute_edit` has duplicated code paths

The "path escapes" and "normal" branches in `execute_edit` have ~90% identical logic (find_and_replace → check_syntax → diff → write). The escape branch additionally shows a proposed diff before confirmation, but the core edit logic is repeated.

**Fix:** Extract to a helper:
```python
def _apply_edit(content, find_txt, replace_txt, path, rem, auto_mode, 
                allow_escape, sandbox, log_tool_call):
    # single implementation of find→check→diff→write
```

---

### 9. `_Config.context_limits()` cache not invalidated on `/host` change

When the user runs `/host new-url` in the REPL, `_Config._llm_host` is updated but `_context_window`, `_max_tokens`, etc. are **never cleared**. The next `context_limits()` call returns stale values resolved from the old host.

**Fix:** In the `/host` handler:
```python
elif cmd == "/host":
    new_host = arg.strip()
    if new_host:
        _Config._llm_host = new_host
        # Invalidate context cache so it re-polls the new host
        for attr in ('_context_window', '_max_tokens', '_compress_threshold',
                     '_summarize_threshold', '_turn_prefix_tokens'):
            setattr(_Config, attr, None)
```

---

### 10. `_estimate_tokens` underestimates by ignoring message framing overhead

In `localagent.py`:
```python
def _estimate_tokens(self) -> int:
    return sum(count_tokens(str(m.get("content", ""))) for m in self.messages)
```

This ignores the ~4 tokens per-message overhead that `count_tokens_messages()` accounts for. With 50+ messages, this underestimates by ~200 tokens — enough to miss the 92% overflow guard.

**Fix:** Use the existing helper:
```python
from token_counter import count_tokens_messages

def _estimate_tokens(self) -> int:
    return count_tokens_messages(self.messages)
```

---

### 11. `compress_context` truncation too aggressive for error outputs

When truncating action results, only the first 300 chars and last 800 chars are kept. For long build outputs (e.g., compiler errors), the most useful part (middle section with stack traces) is lost.

**Fix:** Increase head/tail or use a smarter strategy that preserves error patterns:
```python
# Keep first 500 chars (context) and last 1500 chars (errors usually at end)
HEAD_CHARS = 500
TAIL_CHARS = 1500
```

---

### 12. `action_parser.py` regex is fragile with attribute order

The `<edit>`/`<write>` pattern requires `path="..."` to appear before the content:
```python
r'^[ \t]*<(edit|write)\b(?=[^>]*\bpath="[^"]+")([^>]*)>'
```

If the model outputs `<write remote="host" path="file.py">` (remote before path), the lookahead still works. But if `path` uses single quotes or has no value, parsing silently fails. The regex also doesn't validate that `<find>` and `<replace>` sub-tags exist for edits.

**Fix:** Add validation and better error messages:
```python
if tag == "edit" and (not find_m or not rep_m):
    _log.warning("Malformed <edit>: missing <find> or <replace> tags")
    continue  # skip this action rather than producing a broken one
```

---

## 🟢 P2 — Reliability / UX

### 13. Missing timeouts in subprocess calls

Several `subprocess.run` calls lack timeout:
- `file_ops.read_file` (SSH cat) — can hang indefinitely on slow networks
- `file_ops.write_file` (SSH write) — same
- `display.set_terminal_title` (tmux call) — minor but could block

**Fix:** Add reasonable timeouts:
```python
p = subprocess.run(
    f"ssh {remote} ...", shell=True, capture_output=True, text=True, timeout=30,
)
```

---

### 14. `SessionManager.list_sessions()` is O(n*m) — reads entire files

For each session file, it loads every line into memory just to count messages and find the last user message. With many sessions or large logs, this is slow.

**Fix:** Read only the first and last lines:
```python
def list_sessions(self) -> list[dict[str, Any]]:
    sessions = []
    for p in sorted(self.log_dir.glob("*.jsonl"), reverse=True):
        with open(p, "r", encoding="utf-8") as f:
            first_line = f.readline()
            # ... parse first line for metadata ...
            f.seek(0, 2)  # seek to end
            size = f.tell()
            # Read last N bytes to find last message
            # ... binary search backward ...
```

---

### 15. System prompt enforces "one shell per reply" but parser allows multiple

The system prompt says: `For <shell> tags: use at most one per reply.` But `parse_xml_actions` happily parses multiple `<shell>` blocks and `run_agent_turn` executes them all in sequence. This silently over-parallelizes without the user's explicit consent (in non-auto mode).

**Fix:** Either enforce single-shell in the parser or update the system prompt to allow batching:
```python
shells = [a for a in actions if a["type"] == "shell"]
if len(shells) > 1 and not self.auto_mode:
    print(f"\033[33m⚠ {len(shells)} shell commands — executing sequentially\033[0m")
```

---

### 16. `format_relative_time` is duplicated in both `display.py` and `session_manager.py`

Identical function in two modules. One should import from the other.

**Fix:** Keep it in `display.py` (the canonical location) and import in `session_manager.py`:
```python
# session_manager.py
from display import format_relative_time
```

---

### 17. AGENTS.md silently skips second file (already in TODO.md P2#8)

If both `./AGENTS.md` and `~/.localagent/AGENTS.md` exist, only the first is loaded due to `break`.

**Fix:** Load all found files:
```python
_loaded = []
for p in [Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"]:
    if p.exists():
        sys_prompt += f"\n\n### AGENTS.md ({p})\n{p.read_text('utf-8').strip()}"
        _loaded.append(str(p))
```

---

### 18. `meta: dict = None` mutable default parameter idiom

While the code does `meta or {}`, the cleaner Python idiom is:
```python
def log_tool_call(self, tool: str, success: bool, meta: dict | None = None):
```

---

### 19. `_container_system_info` uses fragile `|||` delimiter

If any command output contains `|||`, parsing breaks. This is unlikely but could happen with custom scripts.

**Fix:** Use a more robust protocol (e.g., JSON or null-delimited):
```python
probe = f'echo "{{"release":"$(uname -r)"}"'  # structured output
```

---

### 20. `stream_renderer.py` has complex/bug-prone `flush_all` logic

The `flush_all` method has redundant rendering paths and may double-render leftover content:
```python
# Line ~67-81: renders remaining twice through different code paths
remaining = self.md_buffer.rstrip("\n")
if remaining.strip():
    self._handle_remaining(remaining.strip())
# ... then later ...
leftover = self.md_buffer.strip()  # ← md_buffer was already emptied?
```

---

## 🔵 P3 — Code Polish / Architecture

### 21. `run_agent_turn` is a ~80-line god method

It handles: system info injection, pending notes, LLM calling, action parsing, dispatch, context management, terminal UI, interrupt handling, error recovery, and nudging. Hard to unit-test individual pieces.

**Refactoring suggestion:**
```python
def run_agent_turn(self, req: str):
    req = self._inject_context(req)
    self.messages.append({"role": "user", "content": req})
    
    for _ in range(_MAX_ITERATIONS):
        if self._timed_out(turn_start): break
        resp = self._call_llm()
        actions = self._parse_actions(resp)
        if not actions:
            if self._is_done(resp.text): break
            self._nudge_no_action()
            continue
        results = self._dispatch_actions(actions)
        self.messages.append({"role": "user", "content": format_results(results)})
```

### 22. No type stubs / py.typed marker

The project uses `from __future__ import annotations` and has good type hints but no `py.typed` marker file, so mypy/pyright can't find them for external consumers.

### 23. Test files mixed with source in root directory

Test files (`test_*.py`, `*_tests.py`) are in the same directory as source. A `__init__.py` or subdirectory structure would help:
```
src/
  localagent/
    __init__.py
    agent.py
    config.py
    ...
tests/
  test_agent.py
  test_config.py
```

### 24. No `.gitignore` for `__pycache__` is actually present — but no `*.pyc` exclusion check

The `.gitignore` exists and has `__pycache__/`, which is fine. But there's no linting/formatting config (ruff, black) committed to the repo.

### 25. No entry point script / setup.py/pyproject.toml

The project has no installable package metadata. Users run it as `python localagent.py` rather than `localagent`. A minimal `pyproject.toml` would enable:
```toml
[project.scripts]
localagent = "localagent:main"
```

---

## Quick Wins (apply these first)

| # | File | Fix | Effort |
|---|------|-----|--------|
| 1 | `terminal.py` | Delete or fix duplication | 5 min |
| 2 | `localagent.py` | Add `add_note()` method | 30 sec |
| 3 | `localagent.py` | Use `count_tokens_messages()` for estimation | 2 min |
| 4 | `config.py` + `repl.py` | Invalidate context cache on `/host` change | 5 min |
| 5 | `session_manager.py` | Import `format_relative_time` from display | 30 sec |
| 6 | `localagent.py` | Add magic number constants at top of file | 10 min |
| 7 | `file_ops.py` | Fix SSH path quoting with base64 | 15 min |
| 8 | `docker_sandbox.py` | Add timeout to `docker_exec` | 10 min |