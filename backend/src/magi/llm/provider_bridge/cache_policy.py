"""Unified prompt-cache layer: provider-capability-gated cache_control markers.

Caching is a prefix match. The renderer marks the byte-stable head of the
system prompt with ``SYSTEM_PROMPT_CACHE_BOUNDARY`` (everything before it —
identity/boundary/tool-catalog — is stable across turns; everything after —
persona/memory/runtime — varies per turn). Here we:

- gate by provider capability: only vendors whose wire API honors inline
  ``cache_control`` markers get them (Anthropic, Qwen/DashScope; others are
  automatic-only and must NOT receive markers — they'd be ignored or 400);
- for marker vendors, place a single ``ephemeral`` breakpoint on the stable
  head only (the dynamic tail stays unmarked so a per-turn change there never
  invalidates the cached head);
- always strip the internal boundary so it never reaches the model.

Block format (``{"type":"text","text":...,"cache_control":{"type":"ephemeral"}}``)
is identical for Anthropic's top-level ``system`` and the OpenAI-compatible
system message content, so one helper serves both. See #110.
"""

from __future__ import annotations

from typing import Any

from ...config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from ...config.models import ModelVendor

# Vendors whose API honors an inline cache_control marker. Everyone else is
# automatic/implicit-only — sending a marker is useless or rejected, so gate it.
_MARKER_VENDORS: frozenset[ModelVendor] = frozenset(
    {ModelVendor.ANTHROPIC, ModelVendor.DASHSCOPE}
)


def vendor_supports_cache_marker(vendor: ModelVendor | None) -> bool:
    return vendor in _MARKER_VENDORS


def split_on_boundary(system: str) -> tuple[str, str] | None:
    """Split into (stable_head, dynamic_tail) on the boundary, or None if absent.

    Trims the newlines the renderer's line-join leaves around the marker.
    """
    if SYSTEM_PROMPT_CACHE_BOUNDARY not in system:
        return None
    head, _, tail = system.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    return head.rstrip("\n"), tail.lstrip("\n")


def strip_boundary(system: str) -> str:
    """Remove the internal boundary marker, rejoining head and tail."""
    parts = split_on_boundary(system)
    if parts is None:
        return system
    head, tail = parts
    return f"{head}\n{tail}" if tail else head


def cache_marked_system_content(system: str, *, supports_marker: bool) -> str | list[dict[str, Any]]:
    """Return the system content for a request.

    - unsupported vendor: plain ``str`` with the boundary stripped.
    - supported vendor with a boundary: a content-block list with an
      ``ephemeral`` cache_control on the stable head only.
    - supported vendor without a boundary: plain ``str`` (we don't guess which
      part is stable, so no marker — avoids paying cache-write cost with no read).
    """
    if not supports_marker:
        return strip_boundary(system)

    parts = split_on_boundary(system)
    if parts is None:
        return system

    head, tail = parts
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}
    ]
    if tail:
        blocks.append({"type": "text", "text": tail})
    return blocks
