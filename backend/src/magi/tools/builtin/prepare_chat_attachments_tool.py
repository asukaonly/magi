"""Builtin tool for importing local files into managed chat attachments."""
from __future__ import annotations

from typing import Any

from ..schema import (
    ParameterType,
    Tool,
    ToolErrorCode,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class PrepareChatAttachmentsTool(Tool):
    """Import local files into managed chat attachments for the active turn."""

    def __init__(self) -> None:
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="prepare_chat_attachments",
            description="Import local files into managed chat attachments for the current chat turn.",
            category="chat",
            effect_class="local_write",
            effect_replay_policy="reconcilable",
            parameters=[
                ToolParameter(
                    name="file_paths",
                    type=ParameterType.ARRAY,
                    required=True,
                    array_item_type=ParameterType.STRING,
                    description="Absolute local file paths to import as chat attachments.",
                ),
            ],
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        file_paths = parameters.get("file_paths")
        if not isinstance(file_paths, list) or not file_paths:
            return ToolResult(
                success=False,
                error="file_paths must be a non-empty list.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )

        session_id = str(context.env_vars.get("session_id") or "").strip()
        turn_id = str(context.env_vars.get("turn_id") or "").strip()
        if not session_id or not turn_id:
            return ToolResult(
                success=False,
                error="session_id and turn_id are required in the tool execution context.",
                error_code=ToolErrorCode.MISSING_VALUE.value,
            )

        chat_port = context.capabilities.chat if context.capabilities else None
        if chat_port is None:
            return ToolResult(
                success=False,
                error="Chat capability is not available.",
                error_code=ToolErrorCode.EXECUTION_ERROR.value,
            )

        attachments: list[dict[str, object]] = []
        try:
            for item in file_paths:
                file_path = str(item or "").strip()
                if not file_path:
                    raise ValueError("Attachment source file not found.")
                prepared = await chat_port.ingest_local_file(
                    session_id=session_id,
                    turn_id=turn_id,
                    file_path=file_path,
                )
                attachments.append(prepared)
        except ValueError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.INVALID_PATH.value,
            )
        except OSError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code=ToolErrorCode.READ_ERROR.value,
            )

        return ToolResult(
            success=True,
            data={
                "chat_attachments": attachments,
                "summary": f"Prepared {len(attachments)} chat attachment(s).",
            },
        )
