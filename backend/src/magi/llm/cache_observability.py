"""Prompt-cache observation helpers.

This module builds sanitized diagnostics for cache analysis. It never returns
raw prompt text or raw tool schemas; callers get hashes, sizes, and optionally
tool names only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ..config.models import ModelVendor
from ..utils.model_context_messages import (
    current_dynamic_context_messages,
    strip_runtime_context_metadata,
)

_MARKER_VENDORS: frozenset[ModelVendor] = frozenset(
    {ModelVendor.ANTHROPIC, ModelVendor.DASHSCOPE}
)


def _hash_text(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _split_on_boundary(system: str) -> tuple[str, str] | None:
    if SYSTEM_PROMPT_CACHE_BOUNDARY not in system:
        return None
    head, _, tail = system.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    return head.rstrip("\n"), tail.lstrip("\n")


def _extract_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _cache_strategy(
    *,
    vendor: ModelVendor | None,
    event_context: dict[str, Any] | None,
    has_system_text: bool,
    explicit_system_marker: bool,
) -> str:
    if vendor in _MARKER_VENDORS:
        if explicit_system_marker and has_system_text:
            return "system_marker"
        return "none"

    if not has_system_text:
        return "none"

    has_routing_key = bool(
        (event_context or {}).get("session_id")
        or (event_context or {}).get("conversation_id")
        or (event_context or {}).get("thread_id")
    )
    if vendor == ModelVendor.OPENAI and has_routing_key:
        return "prompt_cache_key"
    if vendor == ModelVendor.GROK and has_routing_key:
        return "grok_conversation_id"
    return "automatic_prefix"


def build_cache_observation(
    *,
    system_prompt: str,
    tools: list[dict[str, Any]] | None,
    vendor: ModelVendor | None,
    event_context: dict[str, Any] | None,
    cache_whole_system: bool,
    store_tool_names: bool,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build sanitized prompt-cache diagnostics for one provider request."""

    parts = _split_on_boundary(system_prompt)
    if parts is not None:
        system_head, dynamic_context = parts
        explicit_system_marker = True
    elif cache_whole_system:
        system_head, dynamic_context = system_prompt, ""
        explicit_system_marker = True
    else:
        system_head, dynamic_context = system_prompt, ""
        explicit_system_marker = False

    if not dynamic_context and messages:
        dynamic_messages = current_dynamic_context_messages(messages)
        if dynamic_messages:
            dynamic_context = _canonical_json(
                [strip_runtime_context_metadata(message) for message in dynamic_messages]
            )

    tool_payload = tools or []
    tools_json = _canonical_json(tool_payload)
    tool_names = _extract_tool_names(tool_payload) if store_tool_names else []
    strategy = _cache_strategy(
        vendor=vendor,
        event_context=event_context,
        has_system_text=bool(system_head.strip()),
        explicit_system_marker=explicit_system_marker,
    )

    return {
        "cache_strategy": strategy,
        "cache_eligible": strategy != "none",
        "system_head_hash": _hash_text(system_head),
        "system_head_chars": len(system_head),
        "dynamic_context_hash": _hash_text(dynamic_context),
        "dynamic_context_chars": len(dynamic_context),
        "tools_hash": _hash_text(tools_json),
        "tool_count": len(tool_payload),
        "tool_names": tool_names,
    }


__all__ = ["build_cache_observation"]
