"""Manage the current user's saved picture stickers through chat."""

from __future__ import annotations

from typing import Any

from magi.identity import CANONICAL_LOCAL_USER
from ..schema import (
    ParameterType, Tool, ToolErrorCode, ToolExecutionContext,
    ToolParameter, ToolResult, ToolSchema,
)


class ChatStickersTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="chat_stickers",
            description=(
                "List, save or remove the current user's picture stickers. "
                "Save an uploaded image from this session by attachment_id and a short descriptive name. "
                "Save or remove only when the user requests it; do not collect images automatically. "
                "Send a saved sticker by replying only [[STICKER:sticker_id]]."
            ),
            category="chat", effect_class="local_write", effect_replay_policy="reconcilable",
            parameters=[
                ToolParameter(name="action", type=ParameterType.STRING, required=True,
                              enum=["list", "save", "remove"], description="Library operation."),
                ToolParameter(name="attachment_id", type=ParameterType.STRING, required=False,
                              description="Owned image attachment in the current session; required for save."),
                ToolParameter(name="name", type=ParameterType.STRING, required=False,
                              description="Descriptive sticker name, 1 to 80 characters; required for save."),
                ToolParameter(name="sticker_id", type=ParameterType.STRING, required=False,
                              description="Exact saved sticker ID; required for remove."),
            ],
            tags=["chat", "sticker", "emoji", "image"],
        )

    async def execute(self, parameters: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        action = parameters.get("action")
        if not isinstance(action, str) or action not in {"list", "save", "remove"}:
            return ToolResult(success=False, error="Invalid sticker action.",
                              error_code=ToolErrorCode.INVALID_PARAMETERS.value)
        required = {"list": (), "save": ("attachment_id", "name"), "remove": ("sticker_id",)}[action]
        if any(not isinstance(parameters.get(key), str) or not parameters[key].strip() for key in required):
            return ToolResult(success=False, error="Required sticker parameters are missing.",
                              error_code=ToolErrorCode.INVALID_PARAMETERS.value)
        chat_port = context.capabilities.chat if context.capabilities else None
        session_id = str(context.env_vars.get("session_id") or "").strip()
        if chat_port is None or not session_id:
            return ToolResult(success=False, error="An active chat session is required.",
                              error_code=ToolErrorCode.MISSING_VALUE.value)
        try:
            data = await chat_port.manage_stickers(
                user_id=str(context.env_vars.get("user_id") or CANONICAL_LOCAL_USER),
                session_id=session_id, action=action,
                attachment_id=parameters.get("attachment_id"), name=parameters.get("name"),
                sticker_id=parameters.get("sticker_id"),
            )
        except (ValueError, OSError) as exc:
            return ToolResult(success=False, error=str(exc), error_code=ToolErrorCode.EXECUTION_ERROR.value)
        return ToolResult(success=True, data=data)
