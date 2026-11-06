"""Readable timeline text without exposing machine labels or runtime envelopes."""
from __future__ import annotations

import re
from typing import Any

AGENT_SOURCES = frozenset({"codex_agent_history", "claude_code_agent_history"})
_INTERNAL_LABEL = re.compile(r"(?:^|[ ,、])(?:entity|site|user|episode|cluster):|^[0-9a-f]{16,}$", re.I)
_ENVELOPE = re.compile(
    r"^\s*<(?P<tag>environment_context|skills_instructions|collaboration_mode|"
    r"permissions instructions|external_codex_apps_[a-zA-Z0-9_]+)(?:\s[^>]*)?>",
)
_HANDBOOK = re.compile(r"^\s*# AGENTS\.md instructions for [^\n]+\s*\n+<INSTRUCTIONS>")
_PREFIX = re.compile(r"^(?:Chrome Browsing|Codex conversed|Claude Code conversed)\s*(?:[·:：]\s*)?", re.I)


def readable_label(value: Any) -> str:
    """Reject machine-generated labels; user-owned labels bypass this function."""
    text = str(value or "").strip()
    normalized = text.lower().replace(" ", "_").replace("-", "_")
    if _INTERNAL_LABEL.search(text) or normalized in {
        "activity", "event", "memory", "user", "coding_assistant",
        "codex_agent_history", "claude_code_agent_history", "chrome_history",
    }:
        return ""
    return text


def authored_excerpt(value: str) -> str:
    """Clean a leading runtime envelope while leaving authored quotes intact."""
    text = value
    while text.strip():
        handbook = _HANDBOOK.match(text)
        envelope = _ENVELOPE.match(text)
        if handbook:
            tag, end = "INSTRUCTIONS", handbook.end()
        elif envelope:
            tag, end = envelope.group("tag"), envelope.end()
        else:
            return text.strip()
        closing = text.find(f"</{tag}>", end)
        if closing < 0:
            return ""
        text = text[closing + len(tag) + 3:]
    return ""


def display_text(value: Any, source: str = "") -> str:
    text = str(value or "").strip()
    if source in AGENT_SOURCES or source == "chrome_history":
        text = _PREFIX.sub("", text)
    return authored_excerpt(text) if source in AGENT_SOURCES else text


def prompt_excerpts(payload: str) -> list[str]:
    """Read source-owned user-turn sections from a pinned transcript snapshot."""
    if not re.match(r"^## User turn \d+\s*\n", payload):
        return []
    return [text for part in re.split(r"(?m)^## User turn \d+\s*\n", payload)
            if (text := authored_excerpt(part))]
