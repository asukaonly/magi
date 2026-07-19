"""Surface executors: desktop transcript (B keeps chat-store write) and
external channel (DeliveryRouter)."""
from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

from ..chat.storage.messages import ChatMessageConflictError
from ..chat.task_agent.postprocess.background import persist_completion_message
from ..core.logger import get_logger
from ..delivery.contracts import DeliveryFanoutResult
from .contracts import (
    OutreachIntent,
    OutreachIntentConflictError,
    OutreachKind,
)
from .identity import intent_fingerprint, stable_desktop_message_id

logger = get_logger(__name__)


class ExternalChannelDeliveryError(RuntimeError):
    """Raised when one outreach target does not confirm delivery."""

    def __init__(
        self,
        *,
        target: ChannelTarget,
        result: DeliveryFanoutResult,
    ) -> None:
        self.target = target
        self.result = result
        self.delivery_attempted = (
            bool(result.receipts)
            or not result.failures
            or any(failure.delivery_attempted for failure in result.failures)
        )
        failure_details = "; ".join(str(failure.error) for failure in result.failures)
        detail = failure_details or (
            f"expected one receipt, received {len(result.receipts)}"
        )
        super().__init__(
            f"Outreach delivery failed for channel {target.channel_type!r}: {detail}"
        )


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
        try:
            return await persist_completion_message(
                self._chat_store,
                session_id=intent.origin_session_id or "",
                user_id=intent.user_id,
                role=role,
                message_kind=message_kind,
                body=body,
                payload=intent.payload,
                turn_id=intent.origin_turn_id,
                pending_message_id=intent.pending_message_id,
                created_at_ms=intent.completed_at_ms,
                message_id=stable_desktop_message_id(intent.correlation_id),
                correlation_id=intent.correlation_id,
                identity_fingerprint=intent_fingerprint(intent),
            )
        except ChatMessageConflictError as exc:
            raise OutreachIntentConflictError(
                "Outreach correlation ID was reused with different desktop content"
            ) from exc


class ExternalChannelExecutor:
    def __init__(
        self,
        *,
        delivery_router: Any,
        receipts_store: Any | None,
        delivery_boundary: Callable[[], AbstractAsyncContextManager[None]]
        | None = None,
    ) -> None:
        self._router = delivery_router
        self._receipts_store = receipts_store
        self._delivery_boundary = delivery_boundary

    @asynccontextmanager
    async def _operation_boundary(self) -> AsyncIterator[None]:
        if self._delivery_boundary is None:
            yield
            return
        async with self._delivery_boundary():
            yield

    async def push(self, intent: OutreachIntent, body: str, *, target: ChannelTarget) -> list[DeliveryReceipt]:
        content = DeliveryContent(text=body)
        async with self._operation_boundary():
            result = await self._router.fanout_deliver(
                content=content,
                targets=[target],
            )
        if result.failures or len(result.receipts) != 1:
            raise ExternalChannelDeliveryError(target=target, result=result)
        receipts = list(result.receipts)
        if self._receipts_store is not None:
            try:
                await self._receipts_store.save_receipts(
                    session_id=intent.origin_session_id or "",
                    run_id=f"outreach:{intent.correlation_id}",
                    revision=0,
                    receipts=receipts,
                )
            except Exception:
                logger.warning("outreach: save_receipts failed", exc_info=True)
        return receipts


__all__ = [
    "DesktopTranscriptExecutor",
    "ExternalChannelDeliveryError",
    "ExternalChannelExecutor",
]
