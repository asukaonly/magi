from __future__ import annotations

from magi.bootstrap.context import RuntimeBootstrapContext


class _FakeSchedulerService:
    def __init__(self) -> None:
        self.registrations: list[object] = []

    def register_handler(self, target_type, handler) -> None:  # type: ignore[no-untyped-def]
        self.registrations.append((target_type, handler))


def test_action_schedule_registration_module_lives_in_awareness_layer() -> None:
    from magi.awareness.lifecycle import ActionScheduleRegistrationModule

    assert ActionScheduleRegistrationModule.__module__ == "magi.awareness.lifecycle"


async def test_action_schedule_registration_module_registers_action_dispatch_handler() -> None:
    from magi.awareness.lifecycle import ActionScheduleRegistrationModule
    from magi.scheduler.contracts import ScheduledTargetType

    context = RuntimeBootstrapContext()
    context.scheduler.scheduler_service = _FakeSchedulerService()
    context.agent_runtime.action_emitter = object()

    module = ActionScheduleRegistrationModule(context)
    await module.init()

    assert len(context.scheduler.scheduler_service.registrations) == 1
    assert context.scheduler.scheduler_service.registrations[0][0] == ScheduledTargetType.ACTION_DISPATCH
