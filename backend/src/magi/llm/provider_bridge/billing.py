"""Capture billing conditions without retaining request content or credentials."""

import time
from typing import Any


def capture_billing_context(context: dict[str, Any] | None, kwargs: dict[str, Any]) -> None:
    if context is None:
        return
    body = {**kwargs, **(kwargs.get("extra_body") or {})}
    messages = body.get("messages") or []
    blocks = [body.get("system"), *(message.get("content") for message in messages)]
    explicit = any(
        isinstance(block, list) and any(isinstance(part, dict) and part.get("cache_control") for part in block)
        for block in blocks
    )
    thinking = body.get("enable_thinking")
    if thinking is None and isinstance(body.get("thinking"), dict):
        thinking = body["thinking"].get("type") != "disabled"
    context["billing"] = {
        "requested_at": time.time(),
        "thinking": thinking,
        "cache_mode": "explicit" if explicit else "implicit",
        "cache_ttl": (body.get("prompt_cache_options") or {}).get("ttl"),
        "service_tier": body.get("service_tier") or body.get("speed") or "default",
        "inference_geo": body.get("inference_geo") or "global",
    }
