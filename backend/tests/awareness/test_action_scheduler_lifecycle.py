from __future__ import annotations

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.plugins.actions import ActionRegistry


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.registrations: list[object] = []

    def register_handler(self, target_type, handler) -> None:  # type: ignore[no-untyped-def]
        self.registrations.append((target_type, handler))


async def test_action_schedule_registration_module_registers_action_dispatch_handler() -> None:
    from magi.awareness.lifecycle import ActionScheduleRegistrationModule
    from magi.scheduler.contracts import ScheduledTargetType

    context = RuntimeBootstrapContext()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.agent_runtime.action_emitter = object()
    context.plugins.action_registry = ActionRegistry()

    module = ActionScheduleRegistrationModule(context)
    await module.init()

    assert len(context.scheduler.scheduler_service.registrations) == 1
    assert context.scheduler.scheduler_service.registrations[0][0] == ScheduledTargetType.ACTION_DISPATCH
