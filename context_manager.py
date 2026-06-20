from __future__ import annotations

import re


def _extract_file_paths(content: str) -> tuple[list[str], list[str]]:
    """Extract file paths from action results and assistant messages."""
    read_files = []
    modified_files = []

    # From edit/write action results
    for m in re.finditer(r'Successfully edited (\S+)', content):
        if m.group(1) not in modified_files:
            modified_files.append(m.group(1))
    for m in re.finditer(r'Wrote content to (\S+)', content):
        if m.group(1) not in modified_files:
            modified_files.append(m.group(1))
    # From error messages
    for m in re.finditer(r'(?:Error reading|Could not edit file|not found in) (\S+?)(?:\.|\s|$)', content):
        path = m.group(1).rstrip('.,;:')
        if path not in read_files and path not in modified_files:
            read_files.append(path)
    # From shell commands that read files (cat, head, tail, grep, etc.)
    for m in re.finditer(r'(?:^|\s)(?:cat|head|tail|grep|xargs\s+cat)\s+(?:[^|;&\n]*?\s)?([^|;&\n\s\'"]+\.(?:py|js|ts|sh|md|txt|json|yaml|yml|toml|cfg|conf|ini|rs|go|rb|c|h|cpp|hpp|java))', content):
        path = m.group(1)
        if not path.startswith('-') and path not in read_files:
            read_files.append(path)

    return read_files, modified_files


def compress_context(
    messages: list[dict],
    compaction_summary: str,
    config=None,
    llm_request_fn=None,
) -> tuple[list[dict], str]:
    """Compress conversation context by truncating old outputs and summarizing.

    Uses provider-reported token counts when available (from usage blocks on
    assistant messages), falling back to a conservative char-based estimate.
    Supports *incremental* summary updates — feeding the previous summary back
    in so detail is not lost across successive compactions.
    """
    from config import _Config as C

    cfg = config or C
    llm_req = llm_request_fn

    # ------------------------------------------------------------------
    # Token estimation — prefer provider usage when available
    # ------------------------------------------------------------------
    def _estimate_from_usage(messages: list[dict]) -> int:
        """Estimate total context tokens using last assistant usage block."""
        last_usage_idx = None
        last_usage_tokens = 0

        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if m.get("role") == "assistant":
                # Check if this message has attached usage info
                usage = m.get("_usage") or m.get("usage")
                if usage:
                    total = usage.get("total_tokens", 0)
                    if not total:
                        total = (
                            usage.get("prompt_tokens", 0)
                            + usage.get("completion_tokens", 0)
                            + usage.get("cache_read_input_tokens", 0)
                            + usage.get("cache_creation_input_tokens", 0)
                        )
                    if total > 0:
                        last_usage_idx = i
                        last_usage_tokens = total
                    break

        # Estimate trailing tokens (messages after the last usage report)
        trailing = 0
        for i in range((last_usage_idx or -1) + 1, len(messages)):
            trailing += len(str(messages[i].get("content", ""))) // 4

        return last_usage_tokens + trailing if last_usage_idx is not None else _char_estimate(messages)

    def _char_estimate(messages: list[dict]) -> int:
        return sum(len(str(m.get("content", ""))) // 4 for m in messages)

    total_tokens = _estimate_from_usage(messages)

    # ------------------------------------------------------------------
    # Phase 1: Truncate old action-results at compress threshold
    # ------------------------------------------------------------------
    if total_tokens > cfg.compress_threshold():
        for m in messages:
            if m["role"] == "user" and "### Action Results" in str(m.get("content", "")):
                content = m["content"]
                # Keep first 300 chars (command + exit code) and last 800 chars (tail of output)
                if len(content) > 1100:
                    m["content"] = (
                        f"{content[:300]}\n...[Compressed {len(content) - 1100} chars]...\n{content[-800:]}"
                    )

        # Re-estimate after truncation
        total_tokens = _estimate_from_usage(messages)

    # ------------------------------------------------------------------
    # Phase 2: Full summarization at summarize threshold
    # ------------------------------------------------------------------
    if total_tokens > cfg.summarize_threshold():
        # Find split point — keep recent context within turn_prefix budget
        acc, split_idx = 0, 1
        for i in range(len(messages) - 1, -1, -1):
            acc += len(str(messages[i].get("content", ""))) // 4
            if acc > cfg.turn_prefix_tokens():
                split_idx = max(1, i)
                break

        if split_idx >= len(messages) - 1:
            return messages, compaction_summary

        # Collect file paths from the history being summarized
        old_content = "\n".join(str(m.get("content", "")) for m in messages[1:split_idx])
        read_files, modified_files = _extract_file_paths(old_content)

        # Build summarization prompt — incremental if we have a previous summary
        new_part = "Summarize the conversation below:\n" + "\n".join(
            f"[{m['role']}]\n{m['content']}" for m in messages[1:split_idx]
        )

        if compaction_summary:
            # Incremental update — preserve existing summary, add new info
            prompt = (
                "Update the existing session summary below with new conversation turns.\n\n"
                "RULES:\n"
                "- PRESERVE all existing information from the previous summary\n"
                "- ADD new progress, decisions, and context from the new messages\n"
                "- UPDATE the Progress section: move items from 'In Progress' to 'Done' when completed\n"
                "- UPDATE 'Next Steps' based on what was accomplished\n"
                "- PRESERVE exact file paths, function names, and error messages\n"
                "- If something is no longer relevant, you may remove it\n"
                "- Merge new file operations into the Files Read / Files Modified sections\n\n"
                f"<previous-summary>\n{compaction_summary}\n</previous-summary>\n\n"
                f"<new-conversation>\n{new_part}\n</new-conversation>\n\n"
                "Output ONLY the updated summary in the same format."
            )
        else:
            # Fresh summary
            file_info = ""
            if read_files or modified_files:
                file_info = "\n\nFile operations observed:\n"
                if read_files:
                    file_info += f"- Files read: {', '.join(read_files[:20])}\n"
                if modified_files:
                    file_info += f"- Files modified: {', '.join(modified_files[:20])}\n"

            prompt = (
                cfg.summarization_prompt()
                + "\n\n"
                + new_part
                + file_info
            )

        resp = llm_req(
            [
                {"role": "system", "content": cfg.summarization_prompt()},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )

        if resp:
            new_summary = (
                resp.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if new_summary.strip():
                # Append file tracking if we collected it and the summary doesn't have it yet
                file_block = ""
                all_read = read_files
                all_modified = modified_files

                # Also extract from the NEW summary in case LLM added some
                s_reads, s_mods = _extract_file_paths(new_summary)
                for f in s_reads:
                    if f not in all_read:
                        all_read.append(f)
                for f in s_mods:
                    if f not in all_modified:
                        all_modified.append(f)

                if all_read or all_modified:
                    lines = []
                    if all_read:
                        lines.append("\n## Files Read")
                        for f in all_read[:25]:
                            lines.append(f"- {f}")
                    if all_modified:
                        lines.append("\n## Files Modified")
                        for f in all_modified[:25]:
                            lines.append(f"- {f}")
                    if lines:
                        # Only add if not already present
                        if "## Files Read" not in new_summary and "## Files Modified" not in new_summary:
                            file_block = "\n".join(lines)

                compaction_summary = new_summary + file_block
                messages = [
                    messages[0],  # system prompt
                    {
                        "role": "assistant",
                        "content": f"Session context (compacted):\n{compaction_summary}",
                    },
                ] + messages[split_idx:]

    return messages, compaction_summary