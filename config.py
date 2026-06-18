from __future__ import annotations

import os
from pathlib import Path


CLI_VERSION = 5

_COMPRESS_PCT      = 0.50
_SUMMARIZE_PCT     = 0.70
_TURN_PREFIX_PCT   = 0.20
_MAX_TOKENS_PCT    = 0.85

_FALLBACK_N_CTX = 90000
_FALLBACK_MODEL_TAG = ""


def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="localagent",
        description="localagent – AI-powered terminal agent for shell execution, file editing, and writing.",
        epilog="Examples:\n  %(prog)s                Start interactive REPL\n  %(prog)s --yolo                 Start in auto-execute mode\n  %(prog)s --sandbox              Run inside a secure Docker sandbox\n  %(prog)s \"fix the auth bug\"     One-shot: run a task and exit\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-y", "--yolo", action="store_true", help="Enable auto-execute mode (skip y/n confirmations)")
    parser.add_argument("--sandbox", action="store_true", help="Launch the agent in an isolated Docker container")
    parser.add_argument("--cpus", type=float, default=2.0, help="Limit CPU cores for sandbox (default: 2, e.g. 2 or 0.5)")
    parser.add_argument("--memory", type=str, default='4g', help="Limit memory for sandbox (default: 4g, e.g. '4g', '512m')")
    parser.add_argument("--host", default=None, help="LLM host URL (overrides LLM_HOST env var)")
    parser.add_argument("--model", default=None, help="Model name (overrides LLM_MODEL env var)")
    parser.add_argument("--temperature", type=float, default=None, help="Temperature for LLM responses (overrides LLM_TEMPERATURE env var)")
    parser.add_argument("--n-ctx", type=int, default=None, help="Context window size (overrides LLM_N_CTX env var)")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s v{CLI_VERSION}")
    parser.add_argument("task", nargs="?", default=None, help="One-shot task: run it and exit")
    return parser.parse_args(argv)


class _Config:
    """Lazy config – no side effects at import time."""
    _args = None
    _llm_host = None
    _model = None
    _temperature = None
    _context_window = None
    _max_tokens = None
    _compress_threshold = None
    _summarize_threshold = None
    _turn_prefix_tokens = None
    _model_id = None
    _model_quant = None
    _system_prompt = None
    _summarization_prompt = None
    _tmux_window_id = None

    @classmethod
    def args(cls):
        if cls._args is None:
            cls._args = parse_args()
        return cls._args

    @classmethod
    def auto_mode(cls):
        return cls.args().yolo

    @classmethod
    def sandbox(cls):
        return cls.args().sandbox

    @classmethod
    def cpus(cls):
        return cls.args().cpus

    @classmethod
    def memory(cls):
        return cls.args().memory

    @classmethod
    def task(cls):
        return cls.args().task

    @classmethod
    def llm_host(cls):
        if cls._llm_host is None:
            a = cls.args()
            cls._llm_host = a.host or os.getenv("LLM_HOST", "http://localhost:8080")
        return cls._llm_host

    @classmethod
    def model(cls):
        if cls._model is None:
            a = cls.args()
            cls._model = a.model or os.getenv("LLM_MODEL", "local-model")
        return cls._model

    @classmethod
    def temperature(cls):
        if cls._temperature is None:
            a = cls.args()
            cls._temperature = a.temperature if a.temperature is not None else float(os.getenv("LLM_TEMPERATURE", "0.7"))
        return cls._temperature

    @classmethod
    def context_limits(cls):
        """Resolve context limits on first call (triggers model API poll)."""
        if cls._context_window is not None:
            return (cls._context_window, cls._max_tokens, cls._compress_threshold,
                    cls._summarize_threshold, cls._turn_prefix_tokens,
                    cls._model_id, cls._model_quant)
        from llm_client import _resolve_context_limits
        context_window, max_tokens, compress_threshold, summarize_threshold, turn_prefix_tokens, model_id, quant_tag = _resolve_context_limits()
        cls._context_window = context_window
        cls._max_tokens = max_tokens
        cls._compress_threshold = compress_threshold
        cls._summarize_threshold = summarize_threshold
        cls._turn_prefix_tokens = turn_prefix_tokens
        cls._model_id = model_id
        cls._model_quant = quant_tag
        return (cls._context_window, cls._max_tokens, cls._compress_threshold,
                cls._summarize_threshold, cls._turn_prefix_tokens,
                cls._model_id, cls._model_quant)

    @classmethod
    def context_window(cls):
        return cls.context_limits()[0]

    @classmethod
    def max_tokens(cls):
        return cls.context_limits()[1]

    @classmethod
    def compress_threshold(cls):
        return cls.context_limits()[2]

    @classmethod
    def summarize_threshold(cls):
        return cls.context_limits()[3]

    @classmethod
    def turn_prefix_tokens(cls):
        return cls.context_limits()[4]

    @classmethod
    def model_id(cls):
        return cls.context_limits()[5]

    @classmethod
    def model_quant(cls):
        return cls.context_limits()[6]

    @classmethod
    def system_prompt(cls):
        if cls._system_prompt is None:
            cls._system_prompt = Path(__file__).with_name("system_prompt.md").read_text().strip()
        return cls._system_prompt

    @classmethod
    def summarization_prompt(cls):
        if cls._summarization_prompt is None:
            cls._summarization_prompt = Path(__file__).with_name("summarization_prompt.md").read_text().strip()
        return cls._summarization_prompt

    @classmethod
    def tmux_window_id(cls):
        if cls._tmux_window_id is None:
            from shell_executor import run_command
            cls._tmux_window_id = run_command("tmux display-message -p '#{window_id}' 2>/dev/null")
        return cls._tmux_window_id


def _get_args():
    """Backwards-compatible: returns parsed args (lazy)."""
    return _Config.args()