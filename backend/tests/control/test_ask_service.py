from __future__ import annotations

import asyncio
import contextlib

import pytest

from magi.control.ask_service import ControlAskRequest, ControlAskService
from magi.control.common import InteractionBroker
from magi.control.session_store import ControlSessionStore
from magi.core.container import get_container
from magi.events.events import EventTypes


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> bool:
        self.events.append(event)
        return True


@contextlib.contextmanager
def _override(**bindings):
    container = get_container()
    providers = {key: getattr(container, key) for key in bindings}
    for key, value in bindings.items():
        providers[key].override(value)
    try:
        yield
    finally:
        for key in bindings:
            providers[key].reset_override()


@pytest.mark.asyncio
async def test_control_ask_service_owns_answer_lifecycle() -> None:
    store = ControlSessionStore()
    broker = InteractionBroker()
    bus = _RecordingBus()
    service = ControlAskService(session_store=store, interaction_broker=broker)

    async def answer_later() -> None:
        for _ in range(50):
            ask = store.ask_state("sid-service")
            if ask is not None:
                await broker.resolve(
                    interaction_id=ask.request_id,
                    kind="ask",
                    response="yes",
                )
                return
            await asyncio.sleep(0.01)

    with _override(message_bus=bus):
        answerer = asyncio.create_task(answer_later())
        outcome = await service.ask(
            ControlAskRequest(
                session_id="sid-service",
                user_id="local_user",
                turn_id="turn-1",
                question="Proceed?",
                options=["yes", "no"],
                allow_free_text=True,
                timeout_seconds=5,
            )
        )
        await answerer

    assert outcome.answered is True
    assert outcome.answer == "yes"
    assert store.ask_state("sid-service").resolution == "user"
    assert [event.type for event in bus.events] == [
        EventTypes.CONTROL_ASK_REQUESTED,
        EventTypes.CONTROL_ASK_ANSWERED,
    ]


@pytest.mark.asyncio
async def test_choice_only_ask_requires_an_available_option() -> None:
    service = ControlAskService(
        session_store=ControlSessionStore(),
        interaction_broker=InteractionBroker(),
    )

    with pytest.raises(
        ValueError,
        match="choice-only question requires at least one",
    ):
        await service.ask(
            ControlAskRequest(
                session_id="sid-service",
                user_id="local_user",
                turn_id="turn-1",
                question="Proceed?",
                options=[],
                allow_free_text=False,
                timeout_seconds=5,
            )
        )
