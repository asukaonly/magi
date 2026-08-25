"""Chat-owned adapter for the generic model-context runtime port."""

from __future__ import annotations

from typing import Any

from magi.chat.model_context import (
    ModelContextItem,
    ModelContextItemKind,
    ModelContextScope,
    infer_model_context_item_kind,
)
from magi.chat.store import ChatStore
from magi.core.logger import get_logger
from magi.utils.model_context_messages import is_turn_context_message

logger = get_logger(__name__)


class ChatModelContextPort:
    """Translate runtime messages into the chat-owned canonical context log."""

    def __init__(
        self,
        *,
        store: ChatStore,
        session_id: str,
        revision: int,
    ) -> None:
        self._store = store
        self._session_id = str(session_id or "").strip()
        self._revision = int(revision)
        if not self._session_id:
            raise ValueError("Session ID is required for chat model context")

    @property
    def revision(self) -> int:
        return self._revision

    async def commit(
        self,
        *,
        messages: list[dict[str, Any]],
        turn_id: str | None,
        run_id: str,
        step_index: int,
        system_prompt: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        boundary_kind: str | None = None,
    ) -> None:
        items = tuple(_item_from_runtime_message(message) for message in messages)
        previous_revision = self._revision
        snapshot = await self._store.sync_model_context_surface(
            session_id=self._session_id,
            items=items,
            expected_revision=previous_revision,
            turn_id=turn_id,
            run_id=run_id,
            step_index=step_index,
        )
        self._revision = snapshot.revision
        boundary_id: str | None = None
        epoch_id: str | None = None
        if boundary_kind is not None:
            if system_prompt is None or tools is None:
                raise ValueError("Model boundary requires system prompt and tools")
            boundary = await self._store.record_model_context_boundary(
                session_id=self._session_id,
                surface_revision=self._revision,
                system_prompt=system_prompt,
                tools=tools,
                boundary_kind=boundary_kind,
                turn_id=turn_id,
                run_id=run_id,
                step_index=step_index,
            )
            boundary_id = boundary.boundary_id
            epoch_id = boundary.epoch_id
        logger.info(
            "agent_run.model_context_committed",
            session_id=self._session_id,
            run_id=run_id,
            turn_id=turn_id,
            step_index=step_index,
            previous_revision=previous_revision,
            revision=self._revision,
            item_count=len(items),
            changed=self._revision != previous_revision,
            boundary_kind=boundary_kind,
            boundary_id=boundary_id,
            epoch_id=epoch_id,
        )


def _item_from_runtime_message(message: dict[str, Any]) -> ModelContextItem:
    normalized_message = _normalize_message_for_storage(message)
    kind, source, scope = _classify_runtime_message(normalized_message)
    return ModelContextItem.from_prompt_message(
        normalized_message,
        source=source,
        kind=kind,
        scope=scope,
    )


def _classify_runtime_message(
    message: dict[str, Any],
) -> tuple[ModelContextItemKind, str, ModelContextScope]:
    if is_turn_context_message(message):
        return (
            ModelContextItemKind.TURN_CONTEXT,
            "context_assembly",
            ModelContextScope.TURN,
        )
    role = str(message.get("role") or "").strip()
    text = _message_text(message)
    if role == "user" and text.startswith("[Runtime attachment observation]"):
        return (
            ModelContextItemKind.RUNTIME_OBSERVATION,
            "attachment_grounding",
            ModelContextScope.RUN,
        )
    if role == "user" and text.startswith("[Runtime "):
        return (
            ModelContextItemKind.RUNTIME_CONTROL,
            "runtime_control",
            ModelContextScope.RUN,
        )
    if text.startswith("[context compacted]") or text.startswith("[context truncated]"):
        return (
            ModelContextItemKind.COMPACTION_SUMMARY,
            "context_compactor",
            ModelContextScope.SESSION,
        )
    if role == "assistant" and text.startswith("Previous tool activity summary:\n"):
        return (
            ModelContextItemKind.COMPACTION_SUMMARY,
            "tool_history_compactor",
            ModelContextScope.RUN,
        )
    inferred = infer_model_context_item_kind(message)
    source = {
        ModelContextItemKind.USER_MESSAGE: "user",
        ModelContextItemKind.ASSISTANT_MESSAGE: "model",
        ModelContextItemKind.ASSISTANT_TOOL_CALL: "model",
        ModelContextItemKind.TOOL_RESULT: "tool",
    }.get(inferred, "runtime")
    scope = (
        ModelContextScope.RUN
        if inferred in {
            ModelContextItemKind.ASSISTANT_TOOL_CALL,
            ModelContextItemKind.TOOL_RESULT,
        }
        else ModelContextScope.SESSION
    )
    return inferred, source, scope


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = [
        str(block.get("text") or "").strip()
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part)


def _normalize_message_for_storage(message: dict[str, Any]) -> dict[str, Any]:
    """Remove attachment bytes while retaining stable model-visible handles."""

    normalized = dict(message)
    content = message.get("content")
    if not isinstance(content, list):
        return normalized
    blocks: list[Any] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            blocks.append(dict(block) if isinstance(block, dict) else block)
            continue
        attachment_id = str(block.get("attachment_id") or "").strip()
        original_name = str(block.get("original_name") or "").strip()
        mime_type = str(block.get("mime_type") or "image/png").strip() or "image/png"
        details = ["[Attached image reference]"]
        if attachment_id:
            details.append(f"attachment_id={attachment_id}")
        if original_name:
            details.append(f"name={original_name}")
        details.append(f"mime_type={mime_type}")
        blocks.append({"type": "text", "text": " ".join(details)})
    normalized["content"] = blocks
    return normalized


__all__ = ["ChatModelContextPort"]
