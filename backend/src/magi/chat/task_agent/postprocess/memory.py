"""Memory and task-reflection helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol, cast

from magi.agent.post_turn_understanding import AcceptedConversationOutcome
from magi.agent.runtime.contracts import FactRecord
from magi.core.logger import get_logger
from magi.memory.l0.attention_update_scheduler import (
    should_update_attention_immediately,
)
from magi.memory.l3.models import TaskOutcomePacket
from magi.agent.task_agents.common import ExecutionResult, IncomingFactKind
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

logger = get_logger(__name__)


class _MemoryPostprocessHostProtocol(Protocol):
    _background_tasks: set[asyncio.Task[Any]]
    _memory: Any
    _post_turn_understanding_service: Any
    _unified_memory: Any


class ChatPostprocessMemoryMixin:
    """Run chat memory updates and task reflection side effects."""

    async def _record_task_reflection(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        user_message: str,
        response_text: str,
    ) -> bool:
        host = cast(_MemoryPostprocessHostProtocol, self)
        if host._unified_memory is None:
            return False
        if not user_message or not response_text:
            return False
        if not self._should_record_task_reflection(context=context, result=result):
            return False

        event_ids = await self._collect_reflection_event_ids(
            user_id=context.user_id,
            session_id=context.session_id,
        )
        if not event_ids:
            return False

        task_id = str(
            result.orchestration_id
            or (
                context.latest_fact.payload.get("orchestration_id")
                if isinstance(context.latest_fact, FactRecord)
                and isinstance(context.latest_fact.payload, dict)
                else ""
            )
            or f"task_reflection_{int(time.time())}"
        ).strip()
        packet = TaskOutcomePacket(
            task_id=task_id,
            user_id=context.user_id,
            task_kind="user_goal_task",
            task_title=user_message[:120],
            task_status="completed",
            user_goal=user_message,
            result_summary=response_text,
            evidence_event_ids=event_ids,
        )
        try:
            summary = await host._unified_memory.persist_task_outcome_reflection(packet)
            return summary is not None
        except Exception as exc:
            logger.warning("Failed to persist task reflection: %s", exc)
            return False

    def _should_record_task_reflection(
        self,
        *,
        context: ChatRuntimeContext,
        result: ExecutionResult,
    ) -> bool:
        if context.incoming_fact_kind == IncomingFactKind.EXPLORE_TASK_COMPLETED:
            return True
        return context.incoming_fact_kind == IncomingFactKind.WORKER_UPDATE and bool(
            result.orchestration_id
        )

    async def _collect_reflection_event_ids(
        self,
        *,
        user_id: str,
        session_id: str,
        limit: int = 6,
    ) -> list[str]:
        host = cast(_MemoryPostprocessHostProtocol, self)
        l1_store = getattr(host._unified_memory, "l1", None)
        if l1_store is None or not hasattr(l1_store, "query_events"):
            return []
        try:
            events = await l1_store.query_events(
                user_id=user_id,
                session_id=session_id,
                cognition_eligible=True,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Failed to query reflection evidence events: %s", exc)
            return []
        return [
            str(event.get("event_id") or "").strip()
            for event in events
            if str(event.get("event_id") or "").strip()
        ]

    def _schedule_background_memory_updates(
        self,
        *,
        user_id: str,
        user_message: str,
        response_text: str,
        context: ChatRuntimeContext,
        result: ExecutionResult,
        turn_id: str | None = None,
        assistant_message_ids: list[str] | None = None,
        accepted_at: float,
    ) -> bool:
        """Queue shared understanding and task reflection off the response path."""

        host = cast(_MemoryPostprocessHostProtocol, self)
        scheduled_epoch = (
            host._unified_memory.memory_operation_epoch()
            if host._unified_memory is not None
            else 0
        )
        resolved_turn_id = str(turn_id or result.turn_id or "").strip()
        message_payload = (
            result.message_payload
            if isinstance(result.message_payload, dict)
            else {}
        )
        background_task_id = str(
            message_payload.get("background_task_id") or ""
        ).strip()
        background_task_attempt = self._nonnegative_int(
            message_payload.get("background_task_attempt")
        )
        delivery_attempt_no = self._nonnegative_int(
            getattr(context.latest_fact, "delivery_attempt_no", None)
        )
        normalized_message_ids = tuple(
            dict.fromkeys(
                normalized
                for value in assistant_message_ids or ()
                if (normalized := str(value or "").strip())
            )
        )
        primary_message_id = (
            normalized_message_ids[-1]
            if normalized_message_ids
            else ""
        )
        outcome_id = (
            f"chat-message:{primary_message_id}:accepted"
            if primary_message_id
            else (
                f"chat-turn:{resolved_turn_id}:delivery:{delivery_attempt_no}:accepted"
                if delivery_attempt_no is not None
                else f"chat-turn:{resolved_turn_id}:accepted"
            )
        )
        scheduled = False

        async def _enqueue_attention_update() -> None:
            t0 = time.monotonic()
            try:
                service = host._post_turn_understanding_service
                if service is None or not resolved_turn_id:
                    return
                await service.admit(
                    AcceptedConversationOutcome(
                        outcome_id=outcome_id,
                        source_turn_id=resolved_turn_id,
                        user_id=user_id,
                        session_id=context.session_id,
                        user_message=user_message,
                        assistant_response=response_text,
                        epoch=int(scheduled_epoch),
                        accepted_at=accepted_at,
                        persona_id=context.active_persona_id,
                        incoming_fact_kind=self._enum_value(
                            context.incoming_fact_kind
                        ),
                        execution_mode=self._enum_value(result.mode),
                        task_id=background_task_id or None,
                        task_attempt=(
                            background_task_attempt
                            if background_task_id
                            else None
                        ),
                        delivery_attempt_no=delivery_attempt_no,
                        source_message_ids=normalized_message_ids,
                        immediate=should_update_attention_immediately(
                            user_message=user_message,
                            incoming_fact_kind=self._enum_value(
                                context.incoming_fact_kind
                            ),
                        ),
                    )
                )
            except Exception:
                logger.exception(
                    "Failed to enqueue shared post-turn understanding user_id=%s session_id=%s",
                    user_id,
                    context.session_id,
                )
            finally:
                logger.info(
                    "[chat.handle] attention update enqueue finished elapsed_ms=%.1f",
                    (time.monotonic() - t0) * 1000,
                )

        if host._post_turn_understanding_service is not None and resolved_turn_id:
            task = asyncio.create_task(
                _enqueue_attention_update(),
                name=f"chat-outcome-enqueue:{context.session_id}:{outcome_id}",
            )
            host._background_tasks.add(task)
            task.add_done_callback(host._background_tasks.discard)
            scheduled = True

        if (
            host._unified_memory is not None
            and self._should_record_task_reflection(context=context, result=result)
        ):

            async def _run_task_reflection() -> None:
                try:
                    async with host._unified_memory.memory_operation_guard():
                        if (
                            host._unified_memory.memory_operation_epoch()
                            != scheduled_epoch
                        ):
                            return
                        await self._record_task_reflection(
                            context=context,
                            result=result,
                            user_message=user_message,
                            response_text=response_text,
                        )
                except Exception:
                    logger.exception(
                        "Background task reflection failed user_id=%s session_id=%s",
                        user_id,
                        context.session_id,
                    )

            reflection_task = asyncio.create_task(
                _run_task_reflection(),
                name=f"chat-task-reflection:{context.session_id}:{resolved_turn_id}",
            )
            host._background_tasks.add(reflection_task)
            reflection_task.add_done_callback(host._background_tasks.discard)
            scheduled = True

        return scheduled

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    @staticmethod
    def _nonnegative_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None
