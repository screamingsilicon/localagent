from __future__ import annotations

import json
import re
import time
import urllib.request

from config import _Config, _COMPRESS_PCT, _SUMMARIZE_PCT, _TURN_PREFIX_PCT, _MAX_TOKENS_PCT, _FALLBACK_N_CTX, _FALLBACK_MODEL_TAG


def _extract_quant(model_id: str) -> str:
    m = re.search(r'(Q\d+_[A-Z0-9_]+(?:\.\d+)?)', model_id)
    return m.group(1) if m else ""


def _fetch_model_info():
    req = urllib.request.Request(
        f"{_Config.llm_host()}/v1/models",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    retries = 5
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.URLError as e:
            if attempt == retries:
                raise
            wait = 1.0 * attempt
            print(f"[!] /v1/models unreachable (attempt {attempt}/{retries}): {e.reason}. Retrying in {wait:.0f}s...", file=__import__('sys').stderr)
            time.sleep(wait)
    else:
        return _FALLBACK_N_CTX, _FALLBACK_MODEL_TAG, ""

    n_ctx = _FALLBACK_N_CTX
    model_id, quant_tag = _FALLBACK_MODEL_TAG, ""
    for m in data.get("data", []):
        ctx = (m.get("meta", {}).get("n_ctx")
               or m.get("meta", {}).get("n_ctx_train")
               or None)
        if ctx:
            n_ctx = int(ctx)
        mid = m.get("id", "")
        if mid:
            model_id = mid
            quant_tag = _extract_quant(mid)
            break
    return n_ctx, model_id, quant_tag


def _resolve_context_limits():
    try:
        n_ctx, model_id, quant_tag = _fetch_model_info()
    except Exception:
        n_ctx, model_id, quant_tag = _FALLBACK_N_CTX, _FALLBACK_MODEL_TAG, ""

    a = _Config.args()
    n_ctx = a.n_ctx or int(__import__('os').getenv("LLM_N_CTX", n_ctx))

    context_window     = n_ctx
    max_tokens         = int(n_ctx * _MAX_TOKENS_PCT)
    compress_threshold = int(n_ctx * _COMPRESS_PCT)
    summarize_threshold = int(n_ctx * _SUMMARIZE_PCT)
    turn_prefix_tokens = int(n_ctx * _TURN_PREFIX_PCT)

    return context_window, max_tokens, compress_threshold, summarize_threshold, turn_prefix_tokens, model_id, quant_tag


def _model_tag() -> str:
    model_id = _Config.model_id()
    if not model_id:
        return ""
    name = model_id.split(":")[0]
    quant = _Config.model_quant()
    tag = f"{name} ({quant})" if quant else name
    return f"{tag} - {_Config.context_window() // 1000}k ctx"


def llm_request(msgs: list[dict], stream: bool = False, llm_host=None, model=None, temperature=None, max_tokens=None) -> dict | None:
    """Make an LLM request. Can be used standalone or via LocalAgent."""
    import urllib.request as ur
    from config import _Config as C

    host = llm_host or C.llm_host()
    mdl = model or C.model()
    temp = temperature if temperature is not None else C.temperature()
    mtokens = max_tokens or C.max_tokens()

    payload = {
        "model": mdl,
        "messages": msgs,
        "temperature": temp,
        "max_tokens": mtokens,
        "cache_prompt": True
    }
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    req = ur.Request(
        f"{host}/v1/chat/completions",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode()
    )

    HTTP_REQUEST_TIMEOUT = 600
    from display import Spinner, CLEAR_LINE
    spin = Spinner()
    spin.start()

    try:
        if not stream:
            with ur.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as r:
                spin.stop()
                return json.loads(r.read().decode())
        else:
            with ur.urlopen(req, timeout=HTTP_REQUEST_TIMEOUT) as r:
                spin.stop()

                from stream_renderer import StreamRenderer

                usage_data = {}
                timing_data = {}
                renderer = StreamRenderer()

                for line in r:
                    line = line.decode('utf-8').strip()
                    if not line or line.startswith(":"):
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        if "usage" in chunk and chunk["usage"]:
                            usage_data = chunk["usage"]
                        if "timings" in chunk and chunk["timings"]:
                            timing_data = chunk["timings"]

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        reasoning = delta.get("reasoning_content", "")

                        if reasoning:
                            renderer.feed_reasoning(reasoning)

                        if content:
                            renderer.feed_content(content)

                renderer.flush_all()
                return {"content": renderer.full_text, "usage": usage_data, "timings": timing_data}

    except KeyboardInterrupt:
        spin.stop()
        raise
    except Exception as e:
        spin.stop()
        print(f"\033[31m[API Error: {e}]\033[0m")
        return None