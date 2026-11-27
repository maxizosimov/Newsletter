"""One place that talks to the local chat model."""

import json

import httpx

from . import config

_client = httpx.Client(timeout=600)


def ask_json(prompt: str) -> dict:
    r = _client.post(f"{config.OLLAMA_URL}/api/chat", json={
        "model": config.CHAT_MODEL, "stream": False, "format": "json",
        "options": {"temperature": 0.1},
        "messages": [{"role": "user", "content": prompt}],
    })
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def pick(value, allowed, default):
    value = str(value or "").strip().lower()
    return value if value in allowed else default


def clamp_int(value, lo, hi, default):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default
