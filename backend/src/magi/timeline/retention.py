"""Retention helpers for timeline events."""
from __future__ import annotations

from typing import Any


class RetentionService:
    """Builds user-facing retention metadata for timeline facts."""

    def describe_event(self, event: dict[str, Any]) -> dict[str, Any]:
        raw_payload_ref = event.get("raw_payload_ref")
        return {
            "mode": event.get("retention_mode"),
            "retained": bool(raw_payload_ref or event.get("retention_mode") == "retain_raw"),
            "raw_payload_ref": raw_payload_ref,
            "content_block_count": len(event.get("content_blocks", [])),
        }
