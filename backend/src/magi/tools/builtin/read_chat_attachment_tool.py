"""Builtin tool for reading managed chat attachments by attachment id."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from ...utils.runtime import get_runtime_paths
from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)

DEFAULT_ATTACHMENT_READ_LIMIT = 24_000
MAX_ATTACHMENT_READ_LIMIT = 120_000


class ReadChatAttachmentTool(Tool):
    """Read a previously attached managed chat file for the active session."""

    def __init__(self) -> None:
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="read_chat_attachment",
            description=(
                "Read a managed chat attachment from the current session by attachment_id. "
                "Use this when the user asks about an earlier uploaded or generated chat attachment, "
                "such as a PDF report, text file, or image. Prefer file_read for explicit filesystem paths."
            ),
            category="chat",
            parameters=[
                ToolParameter(
                    name="attachment_id",
                    type=ParameterType.STRING,
                    required=True,
                    description="Attachment id from the session attachment references.",
                ),
                ToolParameter(
                    name="session_id",
                    type=ParameterType.STRING,
                    required=False,
                    description="Session id. Defaults to the active chat session.",
                ),
                ToolParameter(
                    name="user_id",
                    type=ParameterType.STRING,
                    required=False,
                    description="User id. Defaults to the active user.",
                ),
                ToolParameter(
                    name="offset",
                    type=ParameterType.INTEGER,
                    required=False,
                    default=0,
                    min_value=0,
                    description="Character offset for text-like attachments.",
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    required=False,
                    default=DEFAULT_ATTACHMENT_READ_LIMIT,
                    min_value=1,
                    description="Maximum characters to return for text-like attachments.",
                ),
            ],
            timeout=20,
            retry_on_failure=False,
            dangerous=False,
            tags=["chat", "attachment", "read"],
            metadata={
                "task_intents": ["inspect_attachment", "recall_context", "answer_from_uploaded_file"],
                "domains": ["chat", "attachments"],
                "operations": ["read", "inspect"],
                "query_shapes": ["attachment_id", "followup_reference"],
                "requires_known_target": True,
                "cost": "medium",
                "tool_hint": (
                    "Use for previously uploaded/generated chat attachments referenced by attachment_id. "
                    "Use file_read instead when the user gives a concrete filesystem path."
                ),
            },
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        attachment_id = str(parameters.get("attachment_id") or "").strip()
        if not attachment_id:
            return ToolResult(
                success=False,
                error="attachment_id is required.",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )
        session_id = str(parameters.get("session_id") or context.env_vars.get("session_id") or "").strip()
        if not session_id:
            return ToolResult(
                success=False,
                error="session_id is required in parameters or tool execution context.",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )
        user_id = str(parameters.get("user_id") or context.env_vars.get("user_id") or DEFAULT_USER_ID).strip()
        offset = _coerce_int(parameters.get("offset"), default=0, minimum=0)
        limit = _coerce_int(
            parameters.get("limit"),
            default=DEFAULT_ATTACHMENT_READ_LIMIT,
            minimum=1,
            maximum=MAX_ATTACHMENT_READ_LIMIT,
        )
        if offset is None or limit is None:
            return ToolResult(
                success=False,
                error="offset and limit must be integers within the supported range.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        chat_port = context.capabilities.chat if context.capabilities else None
        if chat_port is None:
            return ToolResult(
                success=False,
                error="Chat capability is not available.",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        try:
            attachment = chat_port.get_attachment_payload(user_id, session_id, attachment_id)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.INVALID_PARAMETERS.value)
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.EXECUTION_ERROR.value)

        if not isinstance(attachment, dict):
            return ToolResult(
                success=False,
                error="Attachment not found in the current session.",
                error_code=ToolErrorCode.FILE_NOT_FOUND.value,
            )

        metadata = _public_metadata(attachment)
        kind = str(attachment.get("kind") or "file").strip() or "file"
        if kind == "image":
            return ToolResult(
                success=True,
                data={
                    "attachment": metadata,
                    "content_kind": "image",
                    "readable_text": False,
                    "summary": "Image attachment metadata is available. Use a vision-capable turn to inspect image pixels.",
                },
            )

        storage_path = Path(str(attachment.get("storage_path") or "").strip())
        if not storage_path.is_file():
            return ToolResult(
                success=False,
                error="Attachment file not found.",
                error_code=ToolErrorCode.FILE_NOT_FOUND.value,
            )

        source_turn_id = str(attachment.get("turn_id") or context.env_vars.get("turn_id") or "attachment_read").strip()
        text, prepared_payload = self._load_text_content(
            session_id=session_id,
            turn_id=source_turn_id,
            attachment=attachment,
            chat_port=chat_port,
        )
        if text is None:
            parse_error = str(prepared_payload.get("parse_error") or "").strip() if isinstance(prepared_payload, dict) else ""
            return ToolResult(
                success=False,
                error=parse_error or "Attachment content is not readable as text.",
                error_code=ToolErrorCode.READ_ERROR.value,
                data={"attachment": metadata, "parse_status": prepared_payload.get("parse_status") if isinstance(prepared_payload, dict) else None},
            )

        total_chars = len(text)
        visible_text = text[offset : offset + limit]
        next_offset = offset + len(visible_text)
        is_complete = next_offset >= total_chars
        return ToolResult(
            success=True,
            data={
                "attachment": metadata,
                "content_kind": "text",
                "text": visible_text,
                "offset": offset,
                "limit": limit,
                "returned_chars": len(visible_text),
                "total_chars": total_chars,
                "is_complete": is_complete,
                "next_offset": None if is_complete else next_offset,
                "source_truncated": bool(prepared_payload.get("truncated")) if isinstance(prepared_payload, dict) else False,
                "parse_status": prepared_payload.get("parse_status") if isinstance(prepared_payload, dict) else "parsed",
                "page_count": prepared_payload.get("page_count") if isinstance(prepared_payload, dict) else None,
                "summary": _summary_for_text_read(metadata, len(visible_text), total_chars, is_complete),
            },
        )

    def _load_text_content(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment: dict[str, Any],
        chat_port,
    ) -> tuple[str | None, dict[str, Any]]:
        derived_path = _derived_text_path(session_id, turn_id, str(attachment.get("attachment_id") or ""))
        if derived_path.is_file():
            try:
                return derived_path.read_text(encoding="utf-8"), {"parse_status": "parsed"}
            except OSError:
                pass

        prepared = chat_port.prepare_runtime_attachment(
            session_id=session_id,
            turn_id=turn_id,
            attachment=attachment,
        )
        if not isinstance(prepared, dict):
            return None, {}
        path = str(prepared.get("derived_text_path") or "").strip()
        if path:
            try:
                return Path(path).read_text(encoding="utf-8"), prepared
            except OSError:
                return None, prepared
        excerpt = str(prepared.get("derived_text_excerpt") or "")
        if excerpt and str(prepared.get("parse_status") or "") == "parsed":
            return excerpt, prepared
        return None, prepared


def _coerce_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return default
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    if parsed < minimum:
        return None
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _derived_text_path(session_id: str, turn_id: str, attachment_id: str) -> Path:
    return get_runtime_paths().chat_derived_dir / session_id / turn_id / f"{attachment_id}.txt"


def _public_metadata(attachment: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "attachment_id",
        "turn_id",
        "kind",
        "original_name",
        "mime_type",
        "size_bytes",
    )
    return {key: attachment.get(key) for key in keys if attachment.get(key) is not None}


def _summary_for_text_read(
    metadata: dict[str, Any],
    returned_chars: int,
    total_chars: int,
    is_complete: bool,
) -> str:
    name = str(metadata.get("original_name") or "attachment").strip() or "attachment"
    state = "complete" if is_complete else "partial"
    return f"Read {returned_chars} of {total_chars} character(s) from {name} ({state})."
