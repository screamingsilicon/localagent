from __future__ import annotations

import re


def run_repl(agent):
    """Run the interactive REPL loop."""
    from config import _Config
    from display import set_terminal_title, H2_COLOR, BOLD, RESET
    from llm_client import _model_tag

    APP_NAME = "localagent"
    host = re.sub(r'^https?://', '', _Config.llm_host())
    model_tag = _model_tag() if _model_tag() else ""

    parts = [f"\033[1;36m⚡ {APP_NAME}\033[0m"]
    parts.append(f"\033[90m{host}\033[0m")
    if agent.sandbox:
        import docker_sandbox
        parts.append(f"\033[33m[{docker_sandbox.get_container_name()}]\033[0m")
    if model_tag:
        parts.append(f"\033[90m│\033[0m \033[37m{model_tag}\033[0m")
    if agent.auto_mode:
        parts.append(f"\033[1;31m[yolo]\033[0m")

    print(" ".join(parts) + f"  \033[90m(/help)\033[0m")

    while True:
        set_terminal_title(f"❓ {APP_NAME}")
        print(f"\n\033[32m❯ \033[0m", end="", flush=True)
        try:
            lines = [input()]
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n[Interrupted]")
            continue
        while True:
            try:
                lines.append(input())
            except EOFError:
                break
            except KeyboardInterrupt:
                break

        if not (ui := "\n".join(lines).strip()):
            continue

        if ui.startswith("!"):
            out_lines, _ = agent.stream_command_output(ui[1:].strip(), "")
            try:
                if input("\n\aAdd to context? [y/N]: ").strip().lower() == 'y':
                    agent.pending_notes.append(f"$ {ui[1:].strip()}\n" + "\n".join(out_lines[-100:]))
                    print(f"\033[32mAdded to context.\033[0m")
            except KeyboardInterrupt:
                pass

        elif ui.startswith("/"):
            cmd, _, arg = ui.partition(" ")
            if cmd in ("/exit", "/quit"):
                break
            elif cmd == "/help":
                print(f"{H2_COLOR}Available Commands:{RESET}\n  {BOLD}!cmd{RESET}       Run `cmd` locally and optionally add output to context\n  {BOLD}/sessions{RESET} List recent conversation sessions\n  {BOLD}/load <id>{RESET} Load a previous session by its number or ID\n  {BOLD}/clear{RESET}     Clear conversation history (keeps system prompt)\n  {BOLD}/auto{RESET}      Toggle auto-execute mode\n  {BOLD}/host URL{RESET}  Change LLM host\n  {BOLD}/exit{RESET}      Quit the agent")
            elif cmd == "/sessions":
                print(f"\033[36mRecent conversations:\033[0m")
                from display import format_relative_time
                for i, s in enumerate(agent.list_sessions()[:10], 1):
                    c = s["last_user_message"].get("content", "") if s.get("last_user_message") else ""
                    m = re.search(r"### Request\n(.+)", c, re.S)
                    prv = ((m.group(1).replace("\n", " ")[:47] + "...") if m else (c.replace("\n", " ")[:60] + "...")) if c else ""
                    print(f" {i}. \033[36m{format_relative_time(s['last_message_at'])}\033[0m ({s['messages']} msgs)\n    \"{prv}\"")
            elif cmd == "/clear":
                agent.messages = [agent.messages[0]]
                agent._initial_context_sent = False
                print("\033[32mConversation cleared.\033[0m")
            elif cmd == "/auto":
                agent.auto_mode = not agent.auto_mode
                print(f"\033[32mAuto-execute mode: {'ON' if agent.auto_mode else 'OFF'}\033[0m")
            elif cmd == "/host":
                new_host = arg.strip()
                if not new_host:
                    print(f"\033[90mCurrent LLM host: {_Config.llm_host()}\033[0m")
                else:
                    _Config._llm_host = new_host
                    # Invalidate context cache so it re-polls the new host
                    for attr in ("_context_window", "_max_tokens", "_compress_threshold",
                                 "_summarize_threshold", "_turn_prefix_tokens"):
                        setattr(_Config, attr, None)
                    print(f"\033[32mLLM host changed to: {new_host}\033[0m")
            elif cmd == "/load":
                sessions = agent.list_sessions()
                s_id = sessions[int(arg.strip()) - 1]["id"] if arg.strip().isdigit() and 0 <= int(arg.strip()) - 1 < len(sessions) else arg.strip()
                try:
                    loaded = agent._session_mgr.load_session(s_id)
                    agent.messages = [agent.messages[0]] + loaded
                    agent._initial_context_sent = True
                    print(f"\033[32mLoaded {len(loaded)} messages.\033[0m")
                except Exception:
                    print(f"\033[31mSession not found.\033[0m")

        else:
            set_terminal_title(f"⏳ localagent")
            try:
                agent.run_agent_turn(ui)
            except KeyboardInterrupt:
                print(f"\n\033[33m⚠ Turn interrupted (Ctrl+C). Session preserved. Type a new request or /exit.\033[0m")

    print("\nGoodbye!")
    set_terminal_title("")