"""
Worker layer for five-layer architecture.
"""
from __future__ import annotations

from ...core.logger import get_logger
from .action_layer import ActionLayer
from .contracts import LayerResult, TaskEnvelope

logger = get_logger(__name__)


class WorkerLayer:
    """Executes task envelopes through ActionLayer."""

    def __init__(self, action_layer: ActionLayer) -> None:
        self._action_layer = action_layer

    async def execute(self, task: TaskEnvelope) -> LayerResult:
        try:
            return await self._action_layer.execute(task)
        except Exception as exc:
            logger.error(f"WorkerLayer execution failed: {exc}", exc_info=True)
            return LayerResult(success=False, error=str(exc))
