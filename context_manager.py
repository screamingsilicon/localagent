from __future__ import annotations


def compress_context(messages: list[dict], compaction_summary: str, config=None, llm_request_fn=None) -> tuple[list[dict], str]:
    """Compress conversation context by truncating old outputs and summarizing."""
    from config import _Config as C

    cfg = config or C
    llm_req = llm_request_fn

    def est(msgs):
        return sum(len(m.get("content", "")) // 4 for m in msgs)

    if est(messages) > cfg.compress_threshold():
        for m in messages:
            if m["role"] == "user" and "### Action Results" in m["content"]:
                m["content"] = f"{m['content'][:500]}\n...[Compressed]...\n{m['content'][-500:]}"

    if est(messages) > cfg.summarize_threshold():
        acc, split_idx = 0, 1
        for i in range(len(messages) - 1, -1, -1):
            if (acc := acc + len(messages[i].get("content", "")) // 4) > cfg.turn_prefix_tokens():
                split_idx = max(1, i)
                break

        if split_idx >= len(messages) - 1:
            return messages, compaction_summary

        p = "Summarize:\n" + "\n".join(f"[{m['role']}]\n{m['content']}" for m in messages[1:split_idx])
        if compaction_summary:
            p = f"Prev summary:\n{compaction_summary}\n\nNew:\n{p}"

        resp = llm_req(
            [{"role": "system", "content": cfg.summarization_prompt()}, {"role": "user", "content": p}],
            stream=False
        )
        if resp:
            compaction_summary = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            messages = [messages[0], {"role": "assistant", "content": f"Memory Summary:\n{compaction_summary}"}] + messages[split_idx:]

    return messages, compaction_summary