"""Memory and task-reflection helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol, cast

from magi.agent.post_turn_understanding import AcceptedConversationOutcome
from magi.core.logger import get_logger
from magi.memory.l0.attention_update_scheduler import (
    should_update_attention_immediately,
)
from magi.agent.task_agents.common import ExecutionResult
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

logger = get_logger(__name__)


class _MemoryPostprocessHostProtocol(Protocol):
    _background_tasks: set[asyncio.Task[Any]]
    _memory: Any
    _post_turn_understanding_service: Any
    _unified_memory: Any


class ChatPostprocessMemoryMixin:
    """Run shared post-turn understanding outside the response path."""

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
        """Queue shared understanding off the response path."""

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
                        execution_mode=self._enum_value(result.mode) or "agent_run",
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
