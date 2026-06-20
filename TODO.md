# localagent.py — Review & Improvements

## P0 — Critical

### 1. No-op `re.sub` (line ~182)
```python
clean_text = re.sub(r'', '', text)  # Does nothing — empty pattern, empty replacement
```
- **Fix:** Remove the line entirely, or replace with the intended regex (e.g., strip XML comments/whitespace).

### 2. Silent Error Swallowing in `_run_in_container()`
```python
except Exception:
    return ""
```
- **Impact:** Docker failures, timeouts, and permission errors produce no log — agent gets silently wrong/missing system info.
- **Fix:** Log a warning at minimum (`logging.warning` or `print` to stderr). Optionally bubble up for critical calls.

---

## P1 — High

### 3. No Context Window Overflow Protection
- The main loop runs up to 50 iterations with no hard check that `self.messages` fits within `_Config.context_window()`.
- If compaction fails or the LLM returns long outputs, the next request silently exceeds the context window.
- **Fix:** Add a token/token-estimate check before each LLM call; force-compacts or truncates if over threshold.

### 4. Dead Code: `and True` in Tool Detection
```python
if _run_in_container(f"which {tool}") and True:
```
- **Fix:** Remove `and True`.

---

## P2 — Medium

### 5. Inefficient Container Probing (10+ `docker exec` calls)
- `_container_system_info()` spawns a separate subprocess for each fact (`uname`, `python3 --version`, `nproc`, `which` × N, …).
- **Fix:** Batch into a single shell command that returns structured output (e.g., newline-delimited or JSON), then parse once.

### 6. Nudge Messages Pollute Conversation History
```python
self.messages.append({"role": "user", "content": NO_ACTION_NUDGE})
```
- Internal control messages waste context tokens permanently.
- **Fix:** Track nudges separately (counter on the agent) without appending to `self.messages`, or strip them before compaction.

### 7. No Turn Timeout
- The `for _ in range(50)` loop has no time-based guard. A slow LLM or hanging shell command can run indefinitely.
- **Fix:** Add `time.monotonic()` check with a configurable timeout (e.g., 300s).

### 8. Fragile Global Import Pattern
```python
global docker_sandbox
import docker_sandbox  # noqa: PLC0415
```
- Late-bound import inside `system_summary()` crashes with `NameError` if called before setup.
- **Fix:** Inject the dependency or import at module level with a conditional guard.

---

## P3 — Lower Priority

### 9. Compaction Called After Every Action Batch
- `compress_context()` triggers an LLM call on every iteration, adding latency and cost.
- **Fix:** Only compact when context exceeds a threshold (e.g., 70% of window). Consider heuristic/local summarization as fallback.

### 10. Accessing Private Member `_write_log`
```python
self._session_mgr._write_log({"type": "event", ...})
```
- Violates encapsulation; fragile coupling to `SessionManager` internals.
- **Fix:** Expose a public `log_event()` method on `SessionManager`.

### 11. No Input Sanitization
- Shell commands, file paths in `<edit>`/`<write>` — none are validated before execution.
- **Risk:** Destructive commands (`rm -rf /`), writes outside `/workspace`, access to sensitive files.
- **Fix:** Allowlists for dangerous commands, path confinement checks, optional dry-run mode.

### 12. Mixed Concerns in `run_agent_turn`
- Single method handles: LLM calling, action parsing, dispatching, context management, logging, terminal UI, and keyboard interrupt handling.
- **Fix:** Decompose into smaller methods or a state-machine pattern for testability and clarity.

---

## Quick Summary

| # | Issue | Priority |
|---|-------|----------|
| 1 | No-op `re.sub(r'', '', text)` | P0 |
| 2 | Silent error swallowing in `_run_in_container` | P0 |
| 3 | No context window overflow protection | P1 |
| 4 | Dead code (`and True`) | P1 |
| 5 | 10+ docker exec calls for system info | P2 |
| 6 | Nudge messages polluting history | P2 |
| 7 | No turn timeout | P2 |
| 8 | Fragile global import pattern | P2 |
| 9 | Compaction on every batch | P3 |
| 10 | Accessing `_write_log` private method | P3 |
| 11 | No input sanitization | P3 |
| 12 | Mixed concerns in `run_agent_turn` | P3 |