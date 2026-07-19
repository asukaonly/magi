"""Orchestrates compose -> resolve -> govern -> execute, plus outbox drain."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

from ..agent.trace import now_wall_ms
from ..core.logger import get_logger
from .contracts import (
    GovernorVerdict,
    OutreachIntent,
    OutreachIntentConflictError,
)
from .executor import ExternalChannelDeliveryError
from .identity import (
    canonical_intent_json,
    intent_fingerprint,
    normalize_channel_scope,
)

logger = get_logger(__name__)

ComposeFn = Callable[[OutreachIntent], Awaitable[str]]
PersistComposedBodyFn = Callable[[str], Awaitable[None]]


class OutreachService:
    def __init__(
        self,
        *,
        compose: ComposeFn,
        target_resolver: Any,
        governor: Any,
        desktop_executor: Any,
        external_executor: Any,
        outbox: Any,
        delivery_log: Any,
    ) -> None:
        self._compose = compose
        self._resolver = target_resolver
        self._governor = governor
        self._desktop = desktop_executor
        self._external = external_executor
        self._outbox = outbox
        self._log = delivery_log
        self._conversation_operation_lock = asyncio.Lock()

    async def submit(
        self,
        intent: OutreachIntent,
        *,
        prepared_body: str | None = None,
        persist_composed_body: PersistComposedBodyFn | None = None,
    ) -> None:
        async with self._conversation_operation_lock:
            await self._submit(
                intent,
                prepared_body=prepared_body,
                persist_composed_body=persist_composed_body,
            )

    async def _submit(
        self,
        intent: OutreachIntent,
        *,
        prepared_body: str | None,
        persist_composed_body: PersistComposedBodyFn | None,
    ) -> None:
        targets = await self._resolver.resolve(intent)
        body = prepared_body

        async def ensure_body() -> str:
            nonlocal body
            if body is None:
                body = await self._compose(intent)
                if persist_composed_body is not None:
                    await persist_composed_body(body)
            return body

        desktop_failure: Exception | None = None
        if targets.desktop_session_id:
            body = await ensure_body()
            try:
                await self._desktop.write(intent, body)
            except OutreachIntentConflictError:
                raise
            except Exception as exc:
                desktop_failure = exc
                logger.warning("outreach: desktop write failed", exc_info=True)
        if targets.external is not None:
            # External exceptions propagate intentionally — the caller (producer)
            # owns isolation/retry; we do not double-guard here.
            await self._route_external(
                intent,
                body,
                targets.external,
                ensure_body=ensure_body,
            )
        if desktop_failure is not None:
            raise RuntimeError(
                "Outreach desktop completion was not persisted"
            ) from desktop_failure

    async def _push_and_record(self, intent: OutreachIntent, body: str, target: Any) -> None:
        await self._external.push(intent, body, target=target)
        try:
            await self._log.record(
                correlation_id=intent.correlation_id,
                user_id=intent.user_id,
                channel_type=target.channel_type,
                delivered_at_ms=now_wall_ms(),
            )
        except Exception:
            logger.warning(
                "outreach: delivery confirmed but delivery log write failed "
                "| cid=%s channel_type=%s",
                intent.correlation_id,
                target.channel_type,
                exc_info=True,
            )

    async def _route_external(
        self,
        intent: OutreachIntent,
        body: str | None,
        target: Any,
        *,
        ensure_body: Callable[[], Awaitable[str]],
    ) -> None:
        enqueue_result = await self._enqueue_external_intent(
            intent,
            target=target,
            release_at_ms=now_wall_ms(),
        )
        if not enqueue_result.created:
            logger.info(
                "outreach: logical external intent already exists "
                "| cid=%s channel_scope=%s status=%s",
                intent.correlation_id,
                normalize_channel_scope(target.channel_type),
                enqueue_result.status,
            )
            return

        verdict, release_at = await self._governor.evaluate(intent, external_target=target)
        if verdict is GovernorVerdict.PUSH_NOW:
            if body is None:
                body = await ensure_body()
            await self._attempt_outbox_delivery(
                row_id=enqueue_result.row_id,
                intent=intent,
                body=body,
                target=target,
                propagate_failure=True,
            )
        elif verdict is GovernorVerdict.DEFER:
            if release_at is None:
                raise RuntimeError(
                    "Outreach governor deferred delivery without a release time"
                )
            await self._outbox.reschedule(
                enqueue_result.row_id,
                release_at_ms=int(release_at),
            )
        else:
            await self._outbox.mark_status(enqueue_result.row_id, "dropped")
            logger.info("outreach: dropped external push cid=%s", intent.correlation_id)

    async def _enqueue_external_intent(
        self,
        intent: OutreachIntent,
        *,
        target: Any,
        release_at_ms: int,
    ) -> Any:
        """Persist every external outreach before it can reach a channel."""

        intent_json = canonical_intent_json(intent)
        return await self._outbox.enqueue(
            correlation_id=intent.correlation_id,
            channel_scope=normalize_channel_scope(target.channel_type),
            intent_fingerprint=intent_fingerprint(intent),
            intent_json=intent_json,
            release_at_ms=int(release_at_ms),
            created_at_ms=now_wall_ms(),
        )

    async def drain_due(self, *, now_ms: int) -> None:
        async with self._conversation_operation_lock:
            for row in await self._outbox.list_due(now_ms=now_ms):
                try:
                    await self._drain_due_row(row, now_ms=now_ms)
                except Exception:
                    logger.warning(
                        "outreach: deferred row processing failed "
                        "| row_id=%s",
                        row.get("id"),
                        exc_info=True,
                    )

    @asynccontextmanager
    async def conversation_clear_boundary(self) -> AsyncIterator[None]:
        """Wait for delivery to settle and block new outreach during a clear."""

        async with self._conversation_operation_lock:
            yield

    async def _drain_due_row(
        self,
        row: dict[str, Any],
        *,
        now_ms: int,
    ) -> None:
        """Process one due row without allowing it to starve later rows."""

        try:
            intent = OutreachIntent.from_dict(json.loads(row["intent_json"]))
            if (
                str(row["correlation_id"]) != intent.correlation_id
                or str(row["intent_fingerprint"]) != intent_fingerprint(intent)
                or str(row["intent_json"]) != canonical_intent_json(intent)
            ):
                raise ValueError("Outreach outbox identity does not match its content")
        except Exception:
            await self._outbox.mark_status(row["id"], "dropped")
            return

        targets = await self._resolver.resolve(intent)
        if targets.external is None:
            await self._outbox.mark_status(row["id"], "dropped")
            return
        channel_scope = normalize_channel_scope(targets.external.channel_type)
        if channel_scope != str(row["channel_scope"]):
            await self._outbox.mark_status(row["id"], "dropped")
            return
        if await self._log.was_delivered(intent.correlation_id, channel_scope):
            await self._outbox.mark_status(row["id"], "delivered")
            return

        verdict, release_at_ms = await self._governor.evaluate(
            intent,
            external_target=targets.external,
        )
        if verdict is GovernorVerdict.PUSH_NOW:
            body = await self._compose(intent)
            await self._attempt_outbox_delivery(
                row_id=row["id"],
                intent=intent,
                body=body,
                target=targets.external,
                propagate_failure=False,
            )
        elif verdict is GovernorVerdict.DROP:
            await self._outbox.mark_status(row["id"], "dropped")
        elif verdict is GovernorVerdict.DEFER:
            if release_at_ms is None:
                raise RuntimeError(
                    "Outreach governor deferred delivery without a release time"
                )
            await self._outbox.reschedule(
                row["id"],
                release_at_ms=max(int(release_at_ms), int(now_ms) + 1),
            )

    async def _attempt_outbox_delivery(
        self,
        *,
        row_id: int,
        intent: OutreachIntent,
        body: str,
        target: Any,
        propagate_failure: bool,
    ) -> None:
        """Claim one durable row, then invoke at most one external channel call."""

        claimed = await self._outbox.begin_delivery_attempt(row_id)
        if not claimed:
            logger.info(
                "outreach: external row was already claimed | row_id=%s",
                row_id,
            )
            return
        try:
            await self._push_and_record(intent, body, target=target)
        except ExternalChannelDeliveryError as exc:
            if exc.delivery_attempted:
                await self._retain_uncertain_attempt(
                    row_id=row_id,
                    correlation_id=intent.correlation_id,
                )
                logger.warning(
                    "outreach: delivery outcome is uncertain; automatic retry stopped "
                    "| cid=%s row_id=%s",
                    intent.correlation_id,
                    row_id,
                    exc_info=True,
                )
            else:
                await self._restore_unattempted_delivery(
                    row_id=row_id,
                    correlation_id=intent.correlation_id,
                    intent_json=canonical_intent_json(intent),
                )
            if propagate_failure:
                raise
            return
        except Exception:
            await self._retain_uncertain_attempt(
                row_id=row_id,
                correlation_id=intent.correlation_id,
            )
            logger.warning(
                "outreach: delivery outcome is uncertain; automatic retry stopped "
                "| cid=%s row_id=%s",
                intent.correlation_id,
                row_id,
                exc_info=True,
            )
            if propagate_failure:
                raise
            return
        await self._finish_confirmed_delivery(
            row_id=row_id,
            correlation_id=intent.correlation_id,
        )

    async def _retain_uncertain_attempt(
        self,
        *,
        row_id: int,
        correlation_id: str,
    ) -> None:
        """Best-effort label an already claimed attempt without making it retryable."""

        try:
            await self._outbox.mark_status(row_id, "uncertain")
        except Exception:
            logger.warning(
                "outreach: uncertain status write failed; attempting claim retained "
                "and automatic retry remains stopped | cid=%s row_id=%s",
                correlation_id,
                row_id,
                exc_info=True,
            )

    async def _finish_confirmed_delivery(
        self,
        *,
        row_id: int,
        correlation_id: str,
    ) -> None:
        """Best-effort finish a confirmed attempt without reopening it for delivery."""

        try:
            await self._outbox.mark_status(row_id, "delivered")
        except Exception:
            logger.warning(
                "outreach: delivered status write failed; attempting claim retained "
                "and automatic retry remains stopped | cid=%s row_id=%s",
                correlation_id,
                row_id,
                exc_info=True,
            )

    async def _restore_unattempted_delivery(
        self,
        *,
        row_id: int,
        correlation_id: str,
        intent_json: str,
    ) -> None:
        """Return a claimed row to pending only after a proven pre-delivery failure."""

        try:
            restored = await self._outbox.restore_pending_after_unattempted_delivery(
                row_id,
                intent_json=intent_json,
            )
        except Exception:
            logger.warning(
                "outreach: pending restore failed after a pre-delivery error; "
                "attempting claim retained | cid=%s row_id=%s",
                correlation_id,
                row_id,
                exc_info=True,
            )
            return
        if restored:
            logger.warning(
                "outreach: delivery was not attempted and remains pending "
                "| cid=%s row_id=%s",
                correlation_id,
                row_id,
            )
            return
        logger.warning(
            "outreach: pre-delivery failure could not restore the claimed row "
            "| cid=%s row_id=%s",
            correlation_id,
            row_id,
        )
