"""Format MCP resource reads as fenced read-only context blocks.

Used by the chat send pipeline when an MCP resource is attached to a turn
via the `@`-picker (or any caller that holds the result of
`MCPManager.read_resource`). The block is deterministic — same input,
same output — so callers can dedupe or cache without inspecting MCP
internals.

The output shape mirrors the spec in `docs/superpowers/specs/`:

    <mcp_resource uri="..." mimeType="..." server_id="...">
    <text content here, possibly multi-line>
    </mcp_resource>

Binary `blob` payloads are rendered as a one-line summary instead of
inlining base64 — agents should not inline binary into prompts.
"""

from __future__ import annotations

from typing import Any


def format_resource_block(
    server_id: str, read_result: dict[str, Any]
) -> str:
    """Render the result of MCP `resources/read` as a fenced text block.

    `read_result` is the raw JSON-RPC result, which contains a `contents`
    array — each item has at minimum `uri` and `mimeType`, plus either
    `text` or `blob` (base64).
    """
    parts: list[str] = []
    for item in read_result.get("contents") or []:
        uri = item.get("uri", "")
        mime = item.get("mimeType", "text/plain")
        opening = (
            f'<mcp_resource server_id="{_attr(server_id)}" '
            f'uri="{_attr(uri)}" mimeType="{_attr(mime)}">'
        )
        if "text" in item:
            body = str(item["text"]).rstrip("\n")
        elif "blob" in item:
            blob = item["blob"]
            body = f"[binary content omitted, {len(blob)} bytes base64]"
        else:
            body = "[empty resource]"
        parts.append(f"{opening}\n{body}\n</mcp_resource>")
    return "\n\n".join(parts)


def _attr(value: str) -> str:
    """Escape a string for safe inclusion in a tag attribute."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
