"""Read-side DTOs for chat sessions and display history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChatSessionSummary:
    """Typed session summary returned by the chat read model."""

    session_id: str
    title: str
    last_message_preview: str
    last_user_message_preview: str
    title_overridden: bool
    last_timestamp: int
    message_count: int
    workspace_path: str | None = None
    history_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "last_message_preview": self.last_message_preview,
            "last_user_message_preview": self.last_user_message_preview,
            "title_overridden": self.title_overridden,
            "last_timestamp": self.last_timestamp,
            "message_count": self.message_count,
            "workspace_path": self.workspace_path,
            "history_version": self.history_version,
        }


@dataclass(slots=True)
class ChatSessionRenameResult:
    """Typed rename result for session title updates."""

    session_id: str
    title: str

    def to_dict(self) -> dict[str, str]:
        return {
            "session_id": self.session_id,
            "title": self.title,
        }


@dataclass(slots=True)
class SessionWorkspaceUpdateResult:
    """Typed update result for session workspace path changes."""

    session_id: str
    workspace_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_path": self.workspace_path,
        }


@dataclass(frozen=True, slots=True)
class ChatMessageSourceIdentity:
    """Source identity needed before a user deletes one chat message."""

    message_id: str
    session_id: str
    user_id: str
    role: str
    turn_id: str | None
    run_id: str | None = None
    run_revision: int = 0
    source_message_id: str | None = None
    background_task_id: str | None = None


@dataclass(slots=True)
class ChatDisplayMessage:
    """Typed read model for chat history and display timeline messages."""

    role: str
    content: str
    timestamp: int
    kind: str
    attachments: list[dict[str, Any]] | None = None
    message_id: str | None = None
    message_kind: str | None = None
    persona_id: str | None = None
    turn_id: str | None = None
    trace_display_mode: str | None = None
    allow_trace_collapse: bool = False
    trace_summary: dict[str, Any] | None = None
    trace_available: bool = False
    run_state: dict[str, Any] | None = None
    reply_to: dict[str, Any] | None = None
    label: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "message_kind": self.message_kind,
            "persona_id": self.persona_id,
            "turn_id": self.turn_id,
            "kind": self.kind,
            "attachments": list(self.attachments or []),
            "trace_display_mode": self.trace_display_mode,
            "allow_trace_collapse": self.allow_trace_collapse,
            "trace_summary": self.trace_summary,
            "trace_available": self.trace_available,
            "run_state": (
                dict(self.run_state) if isinstance(self.run_state, dict) else None
            ),
            "reply_to": (
                dict(self.reply_to) if isinstance(self.reply_to, dict) else None
            ),
            "label": dict(self.label) if isinstance(self.label, dict) else None,
            "payload": dict(self.payload) if isinstance(self.payload, dict) else None,
        }

    def to_prompt_message(self) -> dict[str, str]:
        content = str(self.content or "").strip()
        attachment_references = _format_prompt_attachment_references(self.attachments or [])
        if attachment_references:
            content = f"{content}\n\n{attachment_references}" if content else attachment_references
        return {
            "role": self.role,
            "content": content,
        }


def _format_prompt_attachment_references(attachments: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("attachment_id") or "").strip()
        if not attachment_id:
            continue
        name = str(attachment.get("original_name") or "attachment").strip() or "attachment"
        kind = str(attachment.get("kind") or "file").strip() or "file"
        details = [
            f"attachment_id={attachment_id}",
            f"name={name}",
            f"kind={kind}",
        ]
        page_count = attachment.get("page_count")
        if isinstance(page_count, int):
            details.append(f"pages={page_count}")
        character_count = attachment.get("character_count")
        if isinstance(character_count, int):
            details.append(f"chars={character_count}")
        parse_status = str(attachment.get("parse_status") or "").strip()
        if parse_status:
            details.append(f"parse_status={parse_status}")
        lines.append("- " + "; ".join(details))
    if not lines:
        return ""
    return "[Message attachment references]\n" + "\n".join(lines)
