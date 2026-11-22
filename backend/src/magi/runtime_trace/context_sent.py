"""In-memory per-turn sanitized snapshot of context actually sent to the LLM.

This store is intentionally in-memory only (bounded LRU) and never persists
raw prompts or user context to disk, honoring P0-3 diagnostic privacy defaults.
"""

from __future__ import annotations

from collections import OrderedDict
import re
from threading import RLock
import time
from typing import Any

from ..utils.log_redaction import redact_log_text

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_MAX_SECTION_PREVIEW_CHARS = 800
_MAX_LIST_ITEMS = 24
_MAX_ITEM_CHARS = 240
_DEFAULT_MAX_ENTRIES = 256


def _extract_markdown_sections(text: str) -> list[dict[str, Any]]:
    """Split a prompt string into sanitized top-level Markdown sections."""
    normalized = str(text or "").strip()
    if not normalized:
        return []

    sections: list[tuple[str, list[str]]] = []
    current_title = "Prompt"
    current_lines: list[str] = []

    for line in normalized.splitlines():
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines or current_title != "Prompt":
        sections.append((current_title, current_lines))

    rendered: list[dict[str, Any]] = []
    for title, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        safe_title = redact_log_text(title)
        safe_body = redact_log_text(body)
        preview = (
            safe_body
            if len(safe_body) <= _MAX_SECTION_PREVIEW_CHARS
            else f"{safe_body[: _MAX_SECTION_PREVIEW_CHARS - 1].rstrip()}…"
        )
        rendered.append(
            {
                "title": safe_title,
                "preview": preview,
                "char_count": len(safe_body),
            }
        )
    return rendered


def _extract_bullet_items_under_heading(
    text: str,
    heading_prefixes: tuple[str, ...],
) -> list[str]:
    """Extract bullet lines appearing under any matching Markdown heading."""
    if not text:
        return []
    items: list[str] = []
    capturing = False
    capture_level = 1

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip().lower()
            if any(title.startswith(prefix) for prefix in heading_prefixes):
                capturing = True
                capture_level = level
                continue
            if capturing and level <= capture_level:
                capturing = False
            continue
        if not capturing or not line:
            continue
        if line.startswith("[System Notice:") or line.startswith("```"):
            continue
        if line.startswith(("- ", "* ")):
            item = line[2:].strip()
        else:
            item = line
        if item:
            safe_item = redact_log_text(item)
            if len(safe_item) > _MAX_ITEM_CHARS:
                safe_item = f"{safe_item[: _MAX_ITEM_CHARS - 1].rstrip()}…"
            items.append(safe_item)
            if len(items) >= _MAX_LIST_ITEMS:
                break
    return items


def _collect_text_from_messages(messages: list[dict[str, Any]]) -> str:
    """Flatten text blocks from provider messages for context section inspection."""
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        parts.append(text)
    return "\n\n".join(parts)


def build_context_sent_snapshot(
    *,
    provider: str,
    model: str,
    is_local_provider: bool,
    redacted: bool,
    system_prompt: str,
    messages: list[dict[str, Any]],
    excluded_local_only_count: int = 0,
    working_context: str = "",
) -> dict[str, Any]:
    """Build a structured, secret-free preview of what was sent to the LLM for one turn."""
    safe_system_prompt = redact_log_text(str(system_prompt or ""))
    combined_messages_text = redact_log_text(_collect_text_from_messages(messages))
    effective_working_context = redact_log_text(str(working_context or ""))
    inspection_corpus = "\n\n".join(
        part
        for part in (safe_system_prompt, effective_working_context, combined_messages_text)
        if part
    )

    recent_life_brief_items = _extract_bullet_items_under_heading(
        inspection_corpus,
        ("recent authorized activity",),
    )
    recalled_memory_items = _extract_bullet_items_under_heading(
        inspection_corpus,
        ("memory library", "retrieved memory", "recalled memory", "historical recall"),
    )

    system_prompt_sections = _extract_markdown_sections(safe_system_prompt)
    working_context_sections = _extract_markdown_sections(
        effective_working_context or combined_messages_text
    )

    return {
        "provider": str(provider or "").strip() or "unknown",
        "model": str(model or "").strip() or "unknown",
        "is_local_provider": bool(is_local_provider),
        "redacted": bool(redacted),
        "excluded_local_only_count": max(0, int(excluded_local_only_count or 0)),
        "recent_life_brief_items": recent_life_brief_items,
        "recalled_memory_items": recalled_memory_items,
        "system_prompt_sections": system_prompt_sections,
        "working_context_sections": working_context_sections,
        "message_count": len(messages or []),
        "captured_at": time.time(),
    }


class ContextSentStore:
    """Thread-safe bounded in-memory LRU cache of per-turn Context Sent snapshots."""

    def __init__(self, *, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max(16, int(max_entries))
        self._lock = RLock()
        self._entries: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    @staticmethod
    def _key(session_id: str | None, turn_id: str | None) -> tuple[str, str] | None:
        norm_turn = str(turn_id or "").strip()
        if not norm_turn:
            return None
        norm_session = str(session_id or "").strip()
        return (norm_session, norm_turn)

    def record(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
        snapshot: dict[str, Any],
    ) -> None:
        key = self._key(session_id, turn_id)
        if key is None:
            return
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                merged = dict(snapshot)
                merged["redacted"] = bool(existing.get("redacted") or snapshot.get("redacted"))
                merged["excluded_local_only_count"] = max(
                    int(existing.get("excluded_local_only_count") or 0),
                    int(snapshot.get("excluded_local_only_count") or 0),
                )
                if not merged.get("recent_life_brief_items") and existing.get("recent_life_brief_items"):
                    merged["recent_life_brief_items"] = list(existing["recent_life_brief_items"])
                if not merged.get("recalled_memory_items") and existing.get("recalled_memory_items"):
                    merged["recalled_memory_items"] = list(existing["recalled_memory_items"])
                self._entries[key] = merged
                self._entries.move_to_end(key)
            else:
                self._entries[key] = dict(snapshot)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)

    def get(
        self,
        *,
        session_id: str | None,
        turn_id: str | None,
    ) -> dict[str, Any] | None:
        key = self._key(session_id, turn_id)
        if key is None:
            return None
        with self._lock:
            found = self._entries.get(key)
            if found is None and key[0]:
                # Fallback match by turn_id alone when callers omit session_id
                found = self._entries.get(("", key[1]))
            if found is None:
                return None
            return dict(found)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_GLOBAL_CONTEXT_SENT_STORE = ContextSentStore()


def get_context_sent_store() -> ContextSentStore:
    """Return the process-wide bounded in-memory ContextSentStore."""
    return _GLOBAL_CONTEXT_SENT_STORE


__all__ = [
    "ContextSentStore",
    "build_context_sent_snapshot",
    "get_context_sent_store",
]
