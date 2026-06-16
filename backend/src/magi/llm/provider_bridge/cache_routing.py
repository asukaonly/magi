"""Provider cache-routing keys.

OpenAI-compatible providers auto-cache by prefix but spread requests across many
backend nodes; a cache lives on the node that wrote it, so pinning a whole
conversation to one node lifts the hit rate. The providers expose a routing
hint keyed on a stable conversation id (magi uses ``session_id``):

- OpenAI: ``prompt_cache_key`` — a top-level body parameter.
- xAI/Grok: ``x-grok-conv-id`` — an HTTP header.

Both are sent through the OpenAI SDK's documented escape hatches (``extra_body``
/ ``extra_headers``) and vendor-gated, so a provider that doesn't know them
never sees them. Anthropic's native path doesn't use these (it caches via
explicit ``cache_control`` markers instead). See #98.
"""

from __future__ import annotations

from typing import Any

from ...config.models import ModelVendor


def routing_key_from_event_context(event_context: dict[str, Any] | None) -> str | None:
    """The stable per-conversation routing key, or None.

    Prefers ``session_id``; falls back to ``correlation_id`` (the turn id) so a
    routing hint is still emitted when no session id is threaded.
    """
    if not event_context:
        return None
    raw = event_context.get("session_id") or event_context.get("correlation_id")
    key = str(raw).strip() if raw is not None else ""
    return key or None


def cache_routing_request_kwargs(
    vendor: ModelVendor | None, routing_key: str | None
) -> dict[str, Any]:
    """Per-vendor request extras (``extra_body`` / ``extra_headers``) that pin a
    conversation to a cache-warm backend. Empty when there's no key or the
    vendor has no routing hint."""
    if not routing_key:
        return {}
    if vendor == ModelVendor.OPENAI:
        return {"extra_body": {"prompt_cache_key": routing_key}}
    if vendor == ModelVendor.GROK:
        return {"extra_headers": {"x-grok-conv-id": routing_key}}
    return {}
