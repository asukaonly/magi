from __future__ import annotations

from magi.bootstrap.context import RuntimeBootstrapContext


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.registrations: list[object] = []

    def register_handler(self, target_type, handler) -> None:  # type: ignore[no-untyped-def]
        self.registrations.append((target_type, handler))


async def test_agent_schedule_registration_module_registers_agent_task_handler() -> None:
    from magi.agent.lifecycle import AgentScheduleRegistrationModule
    from magi.scheduler.contracts import ScheduledTargetType

    context = RuntimeBootstrapContext()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.agent_runtime.task_agent_manager = object()

    module = AgentScheduleRegistrationModule(context)
    await module.init()

    assert len(context.scheduler.scheduler_service.registrations) == 1
    assert context.scheduler.scheduler_service.registrations[0][0] == ScheduledTargetType.AGENT_TASK
