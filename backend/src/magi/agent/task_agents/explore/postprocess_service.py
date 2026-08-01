"""Post-processing and upstream emit for ExploreTaskAgent."""
from __future__ import annotations

import time
from typing import Callable, Optional

from ....core.logger import get_logger
from ....agent.runtime.contracts import FactRecord
from ..common import ExecutionResult, ExploreTaskCompletedPayload
from .constants import EXPLORE_TASK_COMPLETED
from .contracts import ExploreParseOutcome, ExploreRuntimeContext

logger = get_logger(__name__)


class ExplorePostProcessService:
    """Emits completed Explore dossiers upstream as task-agent facts."""

    def __init__(self, *, get_task_agent_manager: Callable[[], object | None]) -> None:
        self._get_task_agent_manager = get_task_agent_manager

    async def handle(self, context: ExploreRuntimeContext, result: ExecutionResult) -> ExploreParseOutcome:
        if result.skip_emit:
            return ExploreParseOutcome(emitted=False)
        response_text = str(result.response_text or "").strip()
        if not response_text:
            return ExploreParseOutcome(emitted=False)
        latest_fact = context.latest_fact
        correlation_id = result.correlation_id or (
            latest_fact.correlation_id if isinstance(latest_fact, FactRecord) else None
        )
        emitted = await self._emit_upstream_fact(
            event_type=EXPLORE_TASK_COMPLETED,
            upstream_task_agent_type=context.upstream_task_agent_type,
            upstream_task_agent_id=context.upstream_task_agent_id,
            payload=ExploreTaskCompletedPayload(
                user_id=context.user_id,
                session_id=context.session_id,
                root_user_message=result.root_user_message or context.latest_user_message,
                markdown_dossier=response_text,
                run_id=getattr(context.latest_payload, "run_id", None),
                run_revision=int(getattr(context.latest_payload, "run_revision", 0) or 0),
                orchestration_id=result.orchestration_id,
                message_started_at=result.message_started_at,
                turn_id=result.turn_id or getattr(context.latest_payload, "turn_id", None),
            ),
            correlation_id=correlation_id,
            user_message_generation=context.user_message_generation,
        )
        return ExploreParseOutcome(emitted=emitted)

    async def _emit_upstream_fact(
        self,
        *,
        event_type: str,
        upstream_task_agent_type: str,
        upstream_task_agent_id: str,
        payload: ExploreTaskCompletedPayload,
        correlation_id: Optional[str],
        user_message_generation: int | None,
    ) -> bool:
        manager = self._get_task_agent_manager()
        if manager is None:
            logger.warning("Failed to deliver ExploreTaskAgent result upstream | error=task agent manager unavailable")
            return False
        current_generation_getter = getattr(
            manager,
            "current_user_message_generation",
            None,
        )
        if (
            user_message_generation is None
            and callable(current_generation_getter)
            and current_generation_getter() is not None
        ):
            logger.warning("Dropped ExploreTaskAgent result without user-message generation")
            return False
        fact = FactRecord(
            agent_id=f"{upstream_task_agent_type}:{upstream_task_agent_id}",
            event_type=event_type,
            payload={
                "user_id": payload.user_id,
                "session_id": payload.session_id,
                "target_task_agent_type": upstream_task_agent_type,
                "target_task_agent_id": upstream_task_agent_id,
                "upstream_task_agent_type": upstream_task_agent_type,
                "upstream_task_agent_id": upstream_task_agent_id,
                **payload.to_dict(),
            },
            agent_type=upstream_task_agent_type,
            agent_instance_id=upstream_task_agent_id,
            timestamp=time.time(),
            correlation_id=correlation_id,
            user_message_generation=user_message_generation,
        )
        return bool(
            await manager.add_fact_to_agent(
                upstream_task_agent_type,
                upstream_task_agent_id,
                fact,
            )
        )
