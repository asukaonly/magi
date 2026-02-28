"""
Coordinator for five-layer architecture.
"""
from __future__ import annotations

from typing import Dict

from ...core.logger import get_logger
from .contracts import LayerContext, LayerResult
from .router_layer import RouterLayer
from .sensor_layer import SensorLayer
from .task_layer import TaskLayer
from .worker_layer import WorkerLayer

logger = get_logger(__name__)


class FiveLayerCoordinator:
    """Coordinates sensor -> router -> task -> worker -> action chain."""

    def __init__(
        self,
        sensor_layer: SensorLayer,
        router_layer: RouterLayer,
        task_layer: TaskLayer,
        worker_layer: WorkerLayer,
    ) -> None:
        self._sensor_layer = sensor_layer
        self._router_layer = router_layer
        self._task_layer = task_layer
        self._worker_layer = worker_layer
        self._running = False
        self._stats: Dict[str, int] = {"processed": 0, "failed": 0}

    async def start(self) -> None:
        if self._running:
            return
        await self._sensor_layer.start()
        self._running = True
        logger.info("FiveLayerCoordinator started")

    async def stop(self) -> None:
        if not self._running:
            return
        await self._sensor_layer.stop()
        self._running = False
        logger.info("FiveLayerCoordinator stopped")

    async def process_context(self, context: LayerContext) -> LayerResult:
        decision = self._router_layer.route(context)
        task = await self._task_layer.build_task(context, decision)
        result = await self._worker_layer.execute(task)
        if result.success:
            self._stats["processed"] += 1
        else:
            self._stats["failed"] += 1
        return result

    async def on_sensor_context(self, context: LayerContext) -> None:
        await self.process_context(context)

    def get_stats(self) -> Dict[str, int]:
        return dict(self._stats)
