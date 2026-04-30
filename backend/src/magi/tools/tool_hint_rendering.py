"""Rendering helpers for structured tool hints."""

from __future__ import annotations

import json
from typing import Any


class ToolHintRenderingMixin:
    """Render tool hint payloads for prompts."""

    def render_guidance_block(self, hint: dict[str, Any] | None, *, heading: str = "Tool Guidance") -> str:
        if not isinstance(hint, dict) or not hint:
            return ""
        lines = [f"# {heading}"]
        task_intent = str(hint.get("task_intent") or "").strip()
        domain = str(hint.get("domain") or "").strip()
        operation = str(hint.get("operation") or "").strip()
        if task_intent:
            lines.append(f"Task intent: {task_intent}")
        if domain:
            lines.append(f"Domain: {domain}")
        if operation:
            lines.append(f"Operation: {operation}")
        target_locality = str(hint.get("target_locality") or "").strip()
        if target_locality:
            lines.append(f"Target locality: {target_locality}")
        preferred_resolution_order = str(hint.get("preferred_resolution_order") or "").strip()
        if preferred_resolution_order:
            lines.append(f"Preferred resolution order: {preferred_resolution_order}")
        if bool(hint.get("requires_clarification")):
            lines.append(
                "Clarification required before leaving the workspace when the target location is ambiguous."
            )
        tool_hints = hint.get("tool_hints")
        if isinstance(tool_hints, list) and tool_hints:
            lines.append("Preferred tool order:")
            for item in tool_hints[:3]:
                if not isinstance(item, dict):
                    continue
                tool_name = str(item.get("tool") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if tool_name and reason:
                    lines.append(f"- {tool_name}: {reason}")
        lines.append("Structured hint JSON:")
        lines.append(json.dumps(hint, ensure_ascii=False))
        return "\n".join(lines)


__all__ = ["ToolHintRenderingMixin"]
