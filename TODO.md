# localagent.py — Review & Improvements

## ✅ Completed Items

| # | Issue | Fix Applied |
|---|-------|-------------|
| **P0#2** | Narrow exception handling in main loop | Added `except Exception` with logging + user-friendly print |
| **P1#3** | `RuntimeWarning: line buffering isn't supported in binary mode` | Added `bufsize=0` to all `subprocess.run`/`Popen` calls using `text=True` in `localagent.py`, `shell_executor.py`, and `docker_sandbox.py` |

## Remaining Items

### P0 — Bugs / Data Loss

#### 1. No session save on clean exit
Sessions are preserved on `Ctrl+C` but if the agent finishes via `<done/>` or turn timeout, there's no explicit flush — risk of losing the last turn on crash/SIGKILL.

**Fix:** Wrap `run_agent_turn` body in `try / finally:` and call `self._session_mgr.save()` in the `finally` block.

```python
def run_agent_turn(self, req: str):
    try:
        # ... existing loop ...
    finally:
        self._session_mgr.save()  # persist on any exit path
```

### P1 — Runtime Warnings / Correctness

#### 4. `pending_notes` is dead code
The list is cleared in `run_agent_turn` but there's no public method to add items. Either it was never wired up or the API was removed.

**Fix:** Add a small accessor so callers (e.g., REPL, task hooks) can queue context:

```python
def add_note(self, note: str):
    """Queue extra context for the next agent turn."""
    self.pending_notes.append(note)
```

### P2 — Reliability / UX

#### 5. Token estimation is overly rough
`len(str(content)) // 4` underestimates for non-Latin scripts and ignores special tokens (system prompt tokens, tool-call delimiters). This can cause premature or delayed compression.

**Fix:** Add an optional `tiktoken`-based estimator with fallback:

```python
def _estimate_tokens(self) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(str(m.get("content", "")))) for m in self.messages)
    except ImportError:
        return sum(len(str(m.get("content", ""))) // 4 for m in self.messages)
```

#### 6. Magic numbers → named constants or config
`50` iterations, `600` timeout, `0.92` / `0.65` thresholds, `3` nudges — hardcoded without documentation.

**Fix:** Extract to module-level constants at the top of the file:

```python
_TURN_TIMEOUT        = 600   # seconds
_MAX_ITERATIONS      = 50
_CONTEXT_OVERFLOW    = 0.92  # force compact above this ratio
_CONTEXT_COMPRESS    = 0.65  # soft compact above this ratio
_MAX_NO_ACTION_NUDGES = 3
```

#### 7. `docker_sandbox` global mutation in `system_summary()`
Using `global docker_sandbox` inside a function is fragile and non-reentrant.

**Fix:** Lazy-load once behind a module-level sentinel:

```python
_docker_sandbox = None

def _get_docker_sandbox():
    global _docker_sandbox
    if _docker_sandbox is None:
        try:
            import docker_sandbox as ds
            _docker_sandbox = ds
        except ImportError:
            return None
    return _docker_sandbox
```

Both `_run_in_container` and `system_summary` call `_get_docker_sandbox()` — no global assignment inside a function body.

#### 8. AGENTS.md silently skips second file
If both `./AGENTS.md` and `~/.localagent/AGENTS.md` exist, only the first is loaded. The user has no idea the other was ignored.

**Fix:** Load all found files and log:

```python
_loaded = []
for p in [Path("AGENTS.md"), Path.home() / ".localagent" / "AGENTS.md"]:
    if p.exists():
        sys_prompt += f"\n\n### AGENTS.md ({p})\n{p.read_text('utf-8').strip()}"
        _loaded.append(str(p))

if len(_loaded) > 1:
    _log.info("Loaded %d AGENTS.md files: %s", len(_loaded), _loaded)
```

### P3 — Code Polish

#### 9. `meta: dict = None` default parameter
Not a real bug (replaced by `meta or {}`) but the cleaner idiom avoids confusion:

```python
def log_tool_call(self, tool: str, success: bool, meta: dict | None = None):
```

#### 10. Mixed concerns in `run_agent_turn`
Single method handles LLM calling, action parsing, dispatch, context management, terminal UI, and interrupt handling. Hard to unit-test individual pieces.

**Fix (future):** Decompose into a small state machine or delegate methods:
- `_inject_system_info(req) → str`
- `_inject_pending_notes(req) → str`
- `_dispatch_actions(actions) → list[str]`
- `_handle_no_action(text) → bool`  # returns True to break