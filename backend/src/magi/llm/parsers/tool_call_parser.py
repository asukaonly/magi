"""Legacy tool call parser for plain text LLM responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class LegacyToolCall:
    """Parsed legacy tool call block from model text."""

    id: str
    name: str
    arguments: Dict[str, Any]


def parse_legacy_tool_calls(content: str) -> List[LegacyToolCall]:
    """Parse legacy XML-like <tool_call> payloads from a model response."""
    if not content:
        return []

    tool_calls: List[LegacyToolCall] = []
    for index, match in enumerate(
        re.finditer(r"<tool_call>(.*?)</tool_call>", content, flags=re.IGNORECASE | re.DOTALL),
        start=1,
    ):
        block = match.group(1).strip()
        if not block:
            continue

        name_part = re.split(r"<arg_key>", block, flags=re.IGNORECASE, maxsplit=1)[0]
        tool_name = re.sub(r"<[^>]+>", "", name_part).strip()
        if not tool_name:
            continue

        arguments: Dict[str, Any] = {}
        for arg_match in re.finditer(
            r"<arg_key>\s*(.*?)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
            block,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            key = arg_match.group(1).strip()
            if not key:
                continue
            raw_value = arg_match.group(2).strip()
            arguments[key] = _coerce_tool_argument_value(raw_value)

        tool_calls.append(
            LegacyToolCall(
                id=f"legacy_call_{index}",
                name=tool_name,
                arguments=arguments,
            )
        )

    return tool_calls


def _coerce_tool_argument_value(raw_value: str) -> Any:
    """Coerce primitive JSON-like strings to Python values, otherwise keep text."""
    value = raw_value.strip()
    if value == "":
        return ""

    maybe_json = value
    if value.lower() in {"true", "false", "null"}:
        maybe_json = value.lower()

    try:
        return json.loads(maybe_json)
    except (TypeError, json.JSONDecodeError):
        return raw_value
