"""Resolve MCP resource attachments before they enter the prompt.

Chat attachments with ``kind="mcp_resource"`` carry only ``{server_id, uri}``
references. Before the prompt builder runs we pre-read each one through
the 60s TTL cache and stash the formatted text in
``attachment["resolved_text"]`` so ``_build_latest_user_message_content``
can emit it as plain text without doing any IO of its own.
"""

from __future__ import annotations

import logging
from typing import Any

from .lifecycle import get_active_manager
from .log_security import redact_mcp_log_text
from .prompt import format_resource_block
from .resource_cache import get_default_cache

logger = logging.getLogger(__name__)


async def resolve_attachment_resources(
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return ``attachments`` with each MCP resource entry enriched with
    a ``resolved_text`` field (or ``resolved_error`` on failure).

    Mutates a shallow copy so callers can keep the original untouched. Items
    whose kind is not ``mcp_resource`` are passed through unchanged.
    """
    if not attachments:
        return []

    out: list[dict[str, Any]] = []
    manager = get_active_manager()
    cache = get_default_cache()

    for original in attachments:
        if not isinstance(original, dict):
            continue
        if str(original.get("kind") or "").strip() != "mcp_resource":
            out.append(original)
            continue

        item = dict(original)
        server_id = str(item.get("server_id") or "").strip()
        uri = str(item.get("uri") or "").strip()
        if not server_id or not uri:
            item["resolved_error"] = "missing server_id or uri"
            out.append(item)
            continue
        if "resolved_text" in item and isinstance(item["resolved_text"], str):
            # Already pre-resolved upstream — keep as is.
            out.append(item)
            continue
        if manager is None:
            item["resolved_error"] = "MCP manager not initialized"
            out.append(item)
            continue

        try:
            result = await cache.get_or_fetch(
                server_id, uri, manager.read_resource
            )
            item["resolved_text"] = format_resource_block(server_id, result)
        except Exception as exc:  # noqa: BLE001 — surface to user
            logger.warning(
                "Failed to read MCP resource server_id=%s uri=%s: %s",
                server_id,
                uri,
                redact_mcp_log_text(exc),
            )
            item["resolved_error"] = redact_mcp_log_text(exc)
        out.append(item)
    return out
