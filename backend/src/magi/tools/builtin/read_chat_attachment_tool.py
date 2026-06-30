"""Builtin tool for reading managed chat attachments by attachment id."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class _AttachmentReadRequest:
    attachment_id: str
    session_id: str
    user_id: str
    offset: int
    limit: int


def _missing_value_result(error: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=error,
        error_code=ToolErrorCode.MISSING_VALUE.value,
    )


def _invalid_parameters_result(error: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=error,
        error_code=ToolErrorCode.INVALID_PARAMETERS.value,
    )


def _file_not_found_result(error: str) -> ToolResult:
    return ToolResult(
        success=False,
        error=error,
        error_code=ToolErrorCode.FILE_NOT_FOUND.value,
    )


def _chat_port(context: ToolExecutionContext) -> Any | None:
    return context.capabilities.chat if context.capabilities else None


def _attachment_kind(attachment: dict[str, Any]) -> str:
    return str(attachment.get("kind") or "file").strip() or "file"


def _source_turn_id(
    attachment: dict[str, Any],
    context: ToolExecutionContext,
) -> str:
    return str(
        attachment.get("turn_id") or context.env_vars.get("turn_id") or "attachment_read"
    ).strip()


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
                "task_intents": [
                    "inspect_attachment",
                    "recall_context",
                    "answer_from_uploaded_file",
                ],
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
        request = self._build_read_request(parameters, context)
        if isinstance(request, ToolResult):
            return request

        chat_port = _chat_port(context)
        if chat_port is None:
            return ToolResult(
                success=False,
                error="Chat capability is not available.",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        attachment = self._load_attachment(chat_port, request)
        if isinstance(attachment, ToolResult):
            return attachment

        metadata = _public_metadata(attachment)
        if _attachment_kind(attachment) == "image":
            return self._image_result(metadata)

        storage_path = Path(str(attachment.get("storage_path") or "").strip())
        if not storage_path.is_file():
            return _file_not_found_result("Attachment file not found.")

        return self._read_text_attachment(
            request=request,
            context=context,
            attachment=attachment,
            metadata=metadata,
            chat_port=chat_port,
        )

    def _build_read_request(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> _AttachmentReadRequest | ToolResult:
        attachment_id = str(parameters.get("attachment_id") or "").strip()
        if not attachment_id:
            return _missing_value_result("attachment_id is required.")

        session_id = str(
            parameters.get("session_id") or context.env_vars.get("session_id") or ""
        ).strip()
        if not session_id:
            return _missing_value_result(
                "session_id is required in parameters or tool execution context."
            )

        offset = _coerce_int(parameters.get("offset"), default=0, minimum=0)
        limit = _coerce_int(
            parameters.get("limit"),
            default=DEFAULT_ATTACHMENT_READ_LIMIT,
            minimum=1,
            maximum=MAX_ATTACHMENT_READ_LIMIT,
        )
        if offset is None or limit is None:
            return _invalid_parameters_result(
                "offset and limit must be integers within the supported range."
            )

        return _AttachmentReadRequest(
            attachment_id=attachment_id,
            session_id=session_id,
            user_id=str(
                parameters.get("user_id") or context.env_vars.get("user_id") or DEFAULT_USER_ID
            ).strip(),
            offset=offset,
            limit=limit,
        )

    def _load_attachment(
        self,
        chat_port: Any,
        request: _AttachmentReadRequest,
    ) -> dict[str, Any] | ToolResult:
        try:
            attachment = chat_port.get_attachment_payload(
                request.user_id,
                request.session_id,
                request.attachment_id,
            )
        except ValueError as exc:
            return _invalid_parameters_result(str(exc))
        except RuntimeError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        if not isinstance(attachment, dict):
            return _file_not_found_result("Attachment not found in the current session.")
        return attachment

    def _image_result(self, metadata: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "attachment": metadata,
                "content_kind": "image",
                "readable_text": False,
                "summary": "Image attachment metadata is available. Use a vision-capable turn to inspect image pixels.",
            },
        )

    def _read_text_attachment(
        self,
        *,
        request: _AttachmentReadRequest,
        context: ToolExecutionContext,
        attachment: dict[str, Any],
        metadata: dict[str, Any],
        chat_port: Any,
    ) -> ToolResult:
        source_turn_id = _source_turn_id(attachment, context)
        text, prepared_payload = self._load_text_content(
            session_id=request.session_id,
            turn_id=source_turn_id,
            attachment=attachment,
            chat_port=chat_port,
        )
        if text is None:
            return self._text_read_error(metadata, prepared_payload)

        total_chars = len(text)
        visible_text = text[request.offset : request.offset + request.limit]
        next_offset = request.offset + len(visible_text)
        is_complete = next_offset >= total_chars
        return ToolResult(
            success=True,
            data={
                "attachment": metadata,
                "content_kind": "text",
                "text": visible_text,
                "offset": request.offset,
                "limit": request.limit,
                "returned_chars": len(visible_text),
                "total_chars": total_chars,
                "is_complete": is_complete,
                "next_offset": None if is_complete else next_offset,
                "source_truncated": bool(prepared_payload.get("truncated")),
                "parse_status": prepared_payload.get("parse_status") or "parsed",
                "page_count": prepared_payload.get("page_count"),
                "summary": _summary_for_text_read(
                    metadata,
                    len(visible_text),
                    total_chars,
                    is_complete,
                ),
            },
        )

    def _text_read_error(
        self,
        metadata: dict[str, Any],
        prepared_payload: dict[str, Any],
    ) -> ToolResult:
        parse_error = str(prepared_payload.get("parse_error") or "").strip()
        return ToolResult(
            success=False,
            error=parse_error or "Attachment content is not readable as text.",
            error_code=ToolErrorCode.READ_ERROR.value,
            data={
                "attachment": metadata,
                "parse_status": prepared_payload.get("parse_status"),
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
        derived_path = _derived_text_path(
            session_id, turn_id, str(attachment.get("attachment_id") or "")
        )
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
