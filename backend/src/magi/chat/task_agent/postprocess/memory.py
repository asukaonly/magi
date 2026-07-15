"""Memory and task-reflection helpers for chat post-processing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from magi.agent.runtime.contracts import FactRecord
from magi.core.logger import get_logger
from magi.memory.l3.models import TaskOutcomePacket
from magi.personality.feature_flags import get_personality_feature_flags
from magi.personality.interaction_analyzer import analyze_interaction
from magi.personality.interaction_observation_router import apply_interaction_observations
from magi.agent.task_agents.common import ExecutionResult, IncomingFactKind
from magi.agent.task_agents.handlers.contracts import ChatRuntimeContext

logger = get_logger(__name__)


@dataclass(slots=True)
class _MemoryUpdateRequest:
    user_id: str
    user_message: str
    response_text: str
    incoming_fact_kind: str | None
    execution_mode: str | None
    session_id: str | None
    turn_id: str | None
    persona_id: str | None


class _MemoryPostprocessHostProtocol(Protocol):
    _background_tasks: set[asyncio.Task[Any]]
    _memory: Any
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
    ) -> None:
        """Run memory/reflection updates off the AI_RESPONSE critical path."""
        host = cast(_MemoryPostprocessHostProtocol, self)
        scheduled_epoch = (
            host._unified_memory.memory_operation_epoch()
            if host._unified_memory is not None
            else None
        )

        async def _runner() -> None:
            t0 = time.monotonic()
            try:
                if host._unified_memory is None or scheduled_epoch is None:
                    return
                async with host._unified_memory.memory_operation_guard():
                    if host._unified_memory.memory_operation_epoch() != scheduled_epoch:
                        return
                    if user_message:
                        await self._record_memory_updates(
                            user_id=user_id,
                            user_message=user_message,
                            response_text=response_text,
                            incoming_fact_kind=self._enum_value(context.incoming_fact_kind),
                            execution_mode=self._enum_value(result.mode),
                            session_id=context.session_id,
                            turn_id=result.turn_id,
                            persona_id=context.active_persona_id,
                        )
                    await self._record_task_reflection(
                        context=context,
                        result=result,
                        user_message=user_message,
                        response_text=response_text,
                    )
            except Exception:
                logger.exception(
                    "Background memory update failed user_id=%s session_id=%s",
                    user_id,
                    context.session_id,
                )
            finally:
                logger.info(
                    "[chat.handle] background memory updates finished elapsed_ms=%.1f",
                    (time.monotonic() - t0) * 1000,
                )

        task = asyncio.create_task(
            _runner(),
            name=f"chat-memory-updates:{context.session_id}",
        )
        host._background_tasks.add(task)
        task.add_done_callback(host._background_tasks.discard)

    async def _record_memory_updates(
        self,
        *,
        user_id: str,
        user_message: str,
        response_text: str = "",
        incoming_fact_kind: str | None = None,
        execution_mode: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        persona_id: str | None = None,
    ) -> bool:
        features = get_personality_feature_flags()
        if not (features.state_memory_enabled or features.deep_persona_enabled):
            return False

        request = _MemoryUpdateRequest(
            user_id,
            user_message,
            response_text,
            incoming_fact_kind,
            execution_mode,
            session_id,
            turn_id,
            persona_id,
        )
        self._log_memory_update_scope(request)
        milestone_conditions = await self._load_milestone_conditions(features)
        analysis = await analyze_interaction(
            request.user_message,
            request.response_text,
            milestone_conditions=milestone_conditions,
        )

        updated = await self._process_personality_turn_outcome(
            request,
            analysis,
            milestone_conditions,
        )
        if not analysis.memory_observations:
            return updated

        return (
            await self._apply_memory_observations(request, analysis.memory_observations)
        ) or updated

    def _log_memory_update_scope(self, request: _MemoryUpdateRequest) -> None:
        logger.info(
            "[chat.memory] interaction analysis scope user_id=%s session_id=%s turn_id=%s "
            "incoming_fact_kind=%s execution_mode=%s",
            request.user_id,
            request.session_id,
            request.turn_id,
            request.incoming_fact_kind,
            request.execution_mode,
        )

    async def _load_milestone_conditions(self, features: Any) -> dict[str, str] | None:
        host = cast(_MemoryPostprocessHostProtocol, self)
        if host._memory is None or not features.deep_persona_enabled:
            return None
        try:
            config = await host._memory.get_core_personality()
        except Exception:
            return None
        if not hasattr(config, "milestone_conditions"):
            return None
        return config.milestone_conditions or None

    async def _process_personality_turn_outcome(
        self,
        request: _MemoryUpdateRequest,
        analysis: Any,
        milestone_conditions: dict[str, str] | None,
    ) -> bool:
        host = cast(_MemoryPostprocessHostProtocol, self)
        if host._memory is not None:
            try:
                return bool(
                    await host._memory.process_turn_outcome(
                        user_id=request.user_id,
                        user_message=request.user_message,
                        analysis=analysis,
                        milestone_conditions=milestone_conditions,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to process turn outcome: %s", exc)
        return False

    async def _apply_memory_observations(
        self,
        request: _MemoryUpdateRequest,
        observations: list[Any],
    ) -> bool:
        host = cast(_MemoryPostprocessHostProtocol, self)
        try:
            return bool(
                await apply_interaction_observations(
                    observations=observations,
                    user_id=request.user_id,
                    user_message=request.user_message,
                    unified_memory=host._unified_memory,
                    self_memory=host._memory,
                    persona_id=request.persona_id,
                    session_id=request.session_id,
                    turn_id=request.turn_id,
                )
            )
        except Exception as exc:
            logger.warning("Failed to apply interaction observations: %s", exc)
            return False

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")
