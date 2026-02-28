"""
Agent registry for runtime orchestration.
"""
from __future__ import annotations

from ...events.events import EventTypes
from .contracts import SensorEvent
from .types import CHAT_AGENT_ID, MEMORY_DIGEST_AGENT_ID, DAILY_REPORT_AGENT_ID


class AgentRegistry:
    """Stores runtime agent runners and event-to-agent routing rules."""

    def __init__(self) -> None:
        self._runners = {}

    def register_runner(self, runner) -> None:
        self._runners[runner.agent_id] = runner

    async def start_all(self, fact_store, action_executor) -> None:
        for runner in self._runners.values():
            await runner.start(fact_store=fact_store, action_executor=action_executor)

    async def stop_all(self) -> None:
        for runner in self._runners.values():
            await runner.stop()

    def resolve_targets(self, sensor_event: SensorEvent) -> list[str]:
        if sensor_event.event_type == EventTypes.USER_MESSAGE:
            targets = [CHAT_AGENT_ID, MEMORY_DIGEST_AGENT_ID]
            return [target for target in targets if target in self._runners]

        if sensor_event.event_type == "CRON_EVENT":
            targets = [DAILY_REPORT_AGENT_ID, MEMORY_DIGEST_AGENT_ID]
            return [target for target in targets if target in self._runners]

        if MEMORY_DIGEST_AGENT_ID in self._runners:
            return [MEMORY_DIGEST_AGENT_ID]
        return []

    def list_runner_ids(self) -> list[str]:
        return sorted(self._runners.keys())
