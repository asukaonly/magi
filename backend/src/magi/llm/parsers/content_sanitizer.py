"""Sanitizers for model text payloads before exposing internal responses."""

from __future__ import annotations

import json
import re


def sanitize_llm_text(text: str) -> str:
    """Remove provider/tool protocol artifacts from plain text responses."""
    sanitized = re.sub(r"<antml:function_calls>.*?</antml:function_calls>", "", text, flags=re.DOTALL)
    sanitized = re.sub(r"<antml:tool_result>.*?</antml:tool_result>", "", sanitized, flags=re.DOTALL)
    sanitized = re.sub(r"<tool_result>.*?</tool_result>", "", sanitized, flags=re.DOTALL)
    sanitized = re.sub(r"<tool_call>.*?</tool_call>", "", sanitized, flags=re.DOTALL)
    sanitized = re.sub(r"<invoke>.*?</invoke>", "", sanitized, flags=re.DOTALL)

    cleaned_lines = []
    for line in sanitized.splitlines():
        stripped = line.strip()
        remove_line = False
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                maybe_call = json.loads(stripped)
                remove_line = (
                    isinstance(maybe_call, dict)
                    and isinstance(maybe_call.get("name"), str)
                    and isinstance(maybe_call.get("arguments"), dict)
                    and set(maybe_call.keys()).issubset({"name", "arguments"})
                )
            except Exception:
                remove_line = False
        if not remove_line:
            cleaned_lines.append(line)

    normalized = "\n".join(cleaned_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()
