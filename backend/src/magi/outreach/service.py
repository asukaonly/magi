"""Orchestrates compose -> resolve -> govern -> execute, plus outbox drain."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..agent.trace import now_wall_ms
from ..core.logger import get_logger
from .contracts import GovernorVerdict, OutreachIntent

logger = get_logger(__name__)

ComposeFn = Callable[[OutreachIntent], Awaitable[str]]


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

    async def submit(self, intent: OutreachIntent) -> None:
        body = await self._compose(intent)
        targets = await self._resolver.resolve(intent)
        if targets.desktop_session_id:
            try:
                await self._desktop.write(intent, body)
            except Exception:
                logger.warning("outreach: desktop write failed", exc_info=True)
        if targets.external is not None:
            # External exceptions propagate intentionally — the caller (producer)
            # owns isolation/retry; we do not double-guard here.
            await self._route_external(intent, body, targets.external)

    async def _push_and_record(self, intent: OutreachIntent, body: str, target: Any) -> None:
        await self._external.push(intent, body, target=target)
        await self._log.record(
            correlation_id=intent.correlation_id, user_id=intent.user_id,
            channel_type=target.channel_type, delivered_at_ms=now_wall_ms(),
        )

    async def _route_external(self, intent: OutreachIntent, body: str, target: Any) -> None:
        verdict, release_at = await self._governor.evaluate(intent, external_target=target)
        if verdict is GovernorVerdict.PUSH_NOW:
            await self._push_and_record(intent, body, target)
        elif verdict is GovernorVerdict.DEFER:
            await self._outbox.enqueue(
                intent_json=json.dumps(intent.to_dict(), ensure_ascii=False),
                release_at_ms=int(release_at if release_at is not None else now_wall_ms()),
                created_at_ms=now_wall_ms(),
            )
        else:
            logger.info("outreach: dropped external push cid=%s", intent.correlation_id)

    async def drain_due(self, *, now_ms: int) -> None:
        for row in await self._outbox.list_due(now_ms=now_ms):
            try:
                intent = OutreachIntent.from_dict(json.loads(row["intent_json"]))
            except Exception:
                await self._outbox.mark_status(row["id"], "dropped")
                continue
            targets = await self._resolver.resolve(intent)
            if targets.external is None:
                await self._outbox.mark_status(row["id"], "dropped")
                continue
            body = await self._compose(intent)
            verdict, _ = await self._governor.evaluate(intent, external_target=targets.external)
            if verdict is GovernorVerdict.PUSH_NOW:
                await self._push_and_record(intent, body, target=targets.external)
                await self._outbox.mark_status(row["id"], "delivered")
            elif verdict is GovernorVerdict.DROP:
                await self._outbox.mark_status(row["id"], "dropped")
            # DEFER: leave 'pending'; the governor must eventually converge to
            # PUSH_NOW or DROP (release_at_ms is not updated here, so this row
            # re-enters every drain cycle until it converges).
