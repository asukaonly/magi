"""Foreground/background placement for chat task-agent turns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from magi.agent.background.contracts import BackgroundTaskTriggerSource
from magi.agent.background.dispatcher import (
    BackgroundDecisionContext,
    BackgroundDecisionSource,
)
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
)
from magi.config.loader import get_config
from magi.core.logger import get_logger

if TYPE_CHECKING:
    from magi_plugin_sdk.run_trigger import RunTrigger

logger = get_logger(__name__)


_BACKGROUND_TRIGGER_SOURCE_BY_DECISION: dict[
    BackgroundDecisionSource, BackgroundTaskTriggerSource
] = {
    BackgroundDecisionSource.PLANNER: BackgroundTaskTriggerSource.PLANNER,
    BackgroundDecisionSource.RULE: BackgroundTaskTriggerSource.RULE,
    BackgroundDecisionSource.LLM: BackgroundTaskTriggerSource.CLASSIFIER,
    BackgroundDecisionSource.FALLBACK: BackgroundTaskTriggerSource.RULE,
}


@dataclass(slots=True)
class ChatBackgroundLaunchRequest(ExecutionRequest):
    """Execution request that has already been placed in the background."""

    trigger_source: BackgroundTaskTriggerSource = BackgroundTaskTriggerSource.RULE
    trigger: "RunTrigger | None" = None


class ChatRunPlacementService:
    """Decide whether a chat turn should run in foreground or background."""

    def __init__(
        self,
        *,
        background_dispatcher: Any | None = None,
        background_launch_service: Any | None = None,
        session_run_coordinator: Any | None = None,
    ) -> None:
        self._background_dispatcher = background_dispatcher
        self._background_launch_service = background_launch_service
        self._session_run_coordinator = session_run_coordinator

    async def maybe_prepare_background_launch(
        self,
        request: ExecutionRequest,
    ) -> ChatBackgroundLaunchRequest | None:
        """Return a background launch request when auto placement chooses background."""
        if request.mode is not ExecutionMode.FUNCTION_CALLING:
            return None
        if not self._auto_background_dispatch_enabled():
            return None
        dispatcher = self._background_dispatcher
        if dispatcher is None or self._background_launch_service is None:
            return None
        try:
            decision = await dispatcher.classify(
                BackgroundDecisionContext(
                    user_text=request.context.latest_user_message or "",
                    selected_tools=list(request.tool_selection.tools),
                )
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe to foreground
            logger.warning(
                "background dispatcher failed; staying on foreground | user_id=%s error=%s",
                request.context.user_id,
                exc,
            )
            return None
        if not decision.is_background:
            return None
        run_trigger = self._resolve_run_trigger(
            str(getattr(request.context, "session_id", "") or "").strip()
        )
        return ChatBackgroundLaunchRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            trigger_source=_BACKGROUND_TRIGGER_SOURCE_BY_DECISION.get(
                decision.source,
                BackgroundTaskTriggerSource.RULE,
            ),
            trigger=run_trigger,
        )

    async def launch_background(
        self,
        request: ChatBackgroundLaunchRequest,
    ) -> ExecutionResult | None:
        """Enqueue the background request, falling back to foreground on failure."""
        launch_service = self._background_launch_service
        if launch_service is None:
            return None
        try:
            return await launch_service.enqueue_from_request(
                request,
                trigger_source=request.trigger_source,
                trigger=request.trigger,
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe to foreground
            logger.warning(
                "background launch failed; falling back to foreground | user_id=%s error=%s",
                request.context.user_id,
                exc,
            )
            return None

    @staticmethod
    def _auto_background_dispatch_enabled() -> bool:
        """Return whether chat turns may be auto-routed to background."""
        try:
            return bool(get_config().agent.background_tasks.auto_detect_long_task)
        except Exception as exc:  # noqa: BLE001 - config failure should keep foreground
            logger.warning(
                "background auto-dispatch config unavailable; staying on foreground | error=%s",
                exc,
            )
            return False

    def _resolve_run_trigger(self, session_id: str) -> "RunTrigger | None":
        """Best-effort fetch of the active run's origin trigger."""
        if not session_id:
            return None
        get_active_run = getattr(self._session_run_coordinator, "get_active_run", None)
        if not callable(get_active_run):
            return None
        try:
            active_run = get_active_run(session_id)
        except Exception as exc:  # noqa: BLE001 - provenance is best-effort
            logger.warning(
                "active-run trigger lookup failed; dispatching background task without trigger | "
                "session_id=%s error=%s",
                session_id,
                exc,
            )
            return None
        return getattr(active_run, "trigger", None)


__all__ = ["ChatBackgroundLaunchRequest", "ChatRunPlacementService"]
