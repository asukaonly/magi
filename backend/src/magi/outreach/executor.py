"""Surface executors: desktop transcript (B keeps chat-store write) and
external channel (DeliveryRouter)."""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

from ..chat.task_agent.postprocess.background import persist_completion_message
from ..core.logger import get_logger
from .contracts import OutreachIntent, OutreachKind

logger = get_logger(__name__)


def _role_and_kind(kind: OutreachKind) -> tuple[str, str]:
    if kind is OutreachKind.TASK_COMPLETED:
        return "assistant", "assistant_final"
    return "system", "background_task_completion"


class DesktopTranscriptExecutor:
    """Writes the personified body into the originating session transcript,
    reusing the exact existing persistence semantics (approach B). Swapping
    this for a chat_sse ChannelTarget is the future approach-A migration."""

    def __init__(self, *, chat_store: Any) -> None:
        self._chat_store = chat_store

    async def write(self, intent: OutreachIntent, body: str):
        role, message_kind = _role_and_kind(intent.kind)
        return await persist_completion_message(
            self._chat_store,
            session_id=intent.origin_session_id or "",
            user_id=intent.user_id,
            role=role,
            message_kind=message_kind,
            body=body,
            payload=intent.payload,
            pending_message_id=intent.pending_message_id,
            created_at_ms=intent.completed_at_ms,
        )


class ExternalChannelExecutor:
    def __init__(self, *, delivery_router: Any, receipts_store: Any | None) -> None:
        self._router = delivery_router
        self._receipts_store = receipts_store

    async def push(self, intent: OutreachIntent, body: str, *, target: ChannelTarget) -> list[DeliveryReceipt]:
        content = DeliveryContent(text=body)
        receipts = await self._router.fanout_deliver(content=content, targets=[target])
        if receipts and self._receipts_store is not None:
            try:
                await self._receipts_store.save_receipts(
                    session_id=intent.origin_session_id or "",
                    run_id=f"outreach:{intent.correlation_id}",
                    revision=0,
                    receipts=receipts,
                )
            except Exception:
                logger.warning("outreach: save_receipts failed", exc_info=True)
        return list(receipts or [])
