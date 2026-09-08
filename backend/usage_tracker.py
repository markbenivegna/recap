import json
import os

from backend.paths import USAGE_FILE

# Anthropic's own balance/remaining-credit figure isn't exposed by any API
# for a standard key — this tracks what Recap itself has spent, computed
# from each response's real token usage against published per-model
# pricing (per 1M tokens). It's an estimate of our own usage, not your
# actual account balance.
PRICING_PER_MILLION = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}
DEFAULT_PRICING = PRICING_PER_MILLION["claude-sonnet-5"]

_DEFAULT_STATE = {"total_cost_usd": 0.0, "call_count": 0, "input_tokens": 0, "output_tokens": 0}


def _load():
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE) as f:
                return {**_DEFAULT_STATE, **json.load(f)}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_STATE)


def _save(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f)


def record_usage(model, input_tokens, output_tokens):
    pricing = PRICING_PER_MILLION.get(model, DEFAULT_PRICING)
    cost = (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]

    data = _load()
    data["total_cost_usd"] += cost
    data["call_count"] += 1
    data["input_tokens"] += input_tokens
    data["output_tokens"] += output_tokens
    _save(data)
    return data


def get_usage():
    return _load()


def reset_usage():
    data = dict(_DEFAULT_STATE)
    _save(data)
    return data
