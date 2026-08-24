"""Concurrent full-clear coverage for transient control-plane content."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from magi.control.ask_service import ControlAskRequest, ControlAskService
from magi.control.common import InteractionBroker, InteractionClosedError
from magi.control.permission.brokered_prompter import (
    BrokeredPermissionPrompter,
    PendingPermissionRegistry,
)
from magi.control.permission.contracts import (
    PermissionRequest,
    RiskLevel,
    ToolOrigin,
)
from magi.control.session_store import ControlSessionStore
from magi.control.user_content_clear import ControlUserContentClearCoordinator


class _TranscriptBoundary:
    def __init__(self) -> None:
        self.active = False
        self.entries = 0

    @asynccontextmanager
    async def user_content_clear_boundary(self):
        self.entries += 1
        self.active = True
        try:
            yield
        finally:
            self.active = False


def _permission_request(request_id: str) -> PermissionRequest:
    return PermissionRequest(
        request_id=request_id,
        tool_name="bash",
        arguments={"command": "secret command"},
        risk_level=RiskLevel.HIGH,
        origin=ToolOrigin.CHAT,
        agent_id="chat",
        session_id="session-1",
        turn_id="turn-1",
        workspace=None,
    )


async def _wait_until(predicate, *, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def _coordinator(
    *,
    store: ControlSessionStore,
    registry: PendingPermissionRegistry,
    broker: InteractionBroker,
) -> tuple[ControlUserContentClearCoordinator, _TranscriptBoundary]:
    coordinator = ControlUserContentClearCoordinator(
        session_store=store,
        pending_permissions=registry,
        interaction_broker=broker,
    )
    transcript = _TranscriptBoundary()
    coordinator.bind_transcript_subscriber(transcript)
    return coordinator, transcript


@pytest.mark.asyncio
async def test_clear_rejects_permission_waiters_without_late_resolved_event() -> None:
    store = ControlSessionStore()
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    coordinator, transcript = _coordinator(
        store=store,
        registry=registry,
        broker=broker,
    )
    notifications: list[str] = []

    async def notify(channel: str, payload: dict) -> None:
        _ = payload
        notifications.append(channel)

    prompter = BrokeredPermissionPrompter(
        broker=broker,
        registry=registry,
        notify_callback=notify,
    )
    old_request = _permission_request("same-id")
    old_prompt = asyncio.create_task(prompter(old_request, timeout_seconds=10))
    await _wait_until(
        lambda: registry.get("same-id") is old_request and broker.pending_count() == 1
    )

    await store.enter_plan_mode("session-1")
    await store.mutate_run_plan(
        "session-1",
        run_id="run-1",
        plan_id=None,
        expected_version=0,
        item_mutations=[{"title": "secret todo"}],
    )
    await store.open_ask(
        "session-1",
        question="secret question",
        request_id="old-ask",
    )

    async with coordinator.user_content_clear_boundary():
        assert transcript.active is True
        assert registry.snapshot(session_id="*") == []
        assert broker.pending_count() == 0
        assert store.plan_state("session-1").active is False
        assert store.current_run_plan("session-1") is None
        assert store.ask_state("session-1") is None
        assert (
            await broker.resolve(
                interaction_id="same-id",
                kind="permission",
                response={"outcome": "allowed"},
            )
            is False
        )
        with pytest.raises(InteractionClosedError) as exc:
            await old_prompt
        assert exc.value.reason == "user_content_cleared"

    assert notifications == ["control.permission.requested"]
    assert transcript.active is False
    assert transcript.entries == 1

    fresh_request = _permission_request("same-id")
    fresh_prompt = asyncio.create_task(prompter(fresh_request, timeout_seconds=10))
    await _wait_until(
        lambda: registry.get("same-id") is fresh_request and broker.pending_count() == 1
    )
    assert await broker.resolve(
        interaction_id="same-id",
        kind="permission",
        response={"outcome": "allowed"},
    )
    assert (await fresh_prompt).allow is True
    assert notifications == [
        "control.permission.requested",
        "control.permission.requested",
        "control.permission.resolved",
    ]


@pytest.mark.asyncio
async def test_clear_rejects_old_ask_answer_and_new_ask_still_works() -> None:
    store = ControlSessionStore()
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    coordinator, _ = _coordinator(
        store=store,
        registry=registry,
        broker=broker,
    )
    service = ControlAskService(
        session_store=store,
        interaction_broker=broker,
    )

    def request(question: str) -> ControlAskRequest:
        return ControlAskRequest(
            session_id="session-1",
            user_id="user-1",
            turn_id="turn-1",
            question=question,
            options=["yes", "no"],
            allow_free_text=False,
            timeout_seconds=10,
        )

    old_task = asyncio.create_task(service.ask(request("old secret question")))
    await _wait_until(
        lambda: store.ask_state("session-1") is not None and broker.pending_count() == 1
    )
    old_ask = store.ask_state("session-1")
    assert old_ask is not None

    async with coordinator.user_content_clear_boundary():
        assert store.ask_state("session-1") is None
        assert (
            await broker.resolve(
                interaction_id=old_ask.request_id,
                kind="ask",
                response="late answer",
            )
            is False
        )
        with pytest.raises(InteractionClosedError) as exc:
            await old_task
        assert exc.value.reason == "user_content_cleared"

    fresh_task = asyncio.create_task(service.ask(request("fresh question")))
    await _wait_until(
        lambda: store.ask_state("session-1") is not None and broker.pending_count() == 1
    )
    fresh_ask = store.ask_state("session-1")
    assert fresh_ask is not None
    assert fresh_ask.question == "fresh question"
    assert await broker.resolve(
        interaction_id=fresh_ask.request_id,
        kind="ask",
        response="yes",
    )
    outcome = await fresh_task
    assert outcome.answered is True
    assert outcome.answer == "yes"


@pytest.mark.asyncio
async def test_clear_rejects_permission_request_blocked_before_broker_wait() -> None:
    store = ControlSessionStore()
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    coordinator, _ = _coordinator(
        store=store,
        registry=registry,
        broker=broker,
    )
    notify_started = asyncio.Event()
    release_notify = asyncio.Event()
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()
    notifications: list[str] = []

    async def notify(channel: str, payload: dict) -> None:
        _ = payload
        notifications.append(channel)
        if channel == "control.permission.requested":
            notify_started.set()
            await release_notify.wait()

    prompter = BrokeredPermissionPrompter(
        broker=broker,
        registry=registry,
        notify_callback=notify,
    )
    request = _permission_request("pre-wait")
    prompt = asyncio.create_task(prompter(request, timeout_seconds=10))
    await asyncio.wait_for(notify_started.wait(), timeout=1)
    assert broker.pending_count() == 0

    async def clear() -> None:
        async with coordinator.user_content_clear_boundary():
            clear_entered.set()
            await release_clear.wait()

    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert clear_entered.is_set() is False
    release_notify.set()
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    with pytest.raises(InteractionClosedError) as exc:
        await prompt
    assert exc.value.reason == "user_content_cleared"
    assert registry.get("pre-wait") is None
    assert broker.pending_count() == 0
    assert notifications == ["control.permission.requested"]

    release_clear.set()
    await clear_task


@pytest.mark.asyncio
async def test_clear_rejects_ask_started_before_state_open() -> None:
    store = ControlSessionStore()
    registry = PendingPermissionRegistry()
    broker = InteractionBroker()
    coordinator, _ = _coordinator(
        store=store,
        registry=registry,
        broker=broker,
    )
    service = ControlAskService(
        session_store=store,
        interaction_broker=broker,
    )
    before_open = asyncio.Event()
    release_open = asyncio.Event()

    async def block_before_open(request, wait_tasks) -> bool:
        _ = (request, wait_tasks)
        before_open.set()
        await release_open.wait()
        return False

    service._cancelled_before_open = block_before_open  # type: ignore[method-assign]
    ask_task = asyncio.create_task(
        service.ask(
            ControlAskRequest(
                session_id="session-old",
                user_id="user-1",
                turn_id="turn-1",
                question="old question",
                options=["yes", "no"],
                allow_free_text=False,
                timeout_seconds=10,
            )
        )
    )
    await asyncio.wait_for(before_open.wait(), timeout=1)

    async with coordinator.user_content_clear_boundary():
        release_open.set()
        with pytest.raises(InteractionClosedError) as exc:
            await ask_task
        assert exc.value.reason == "user_content_cleared"
        assert store.ask_state("session-old") is None
        assert broker.pending_count() == 0


@pytest.mark.asyncio
async def test_clear_fails_closed_until_transcript_boundary_is_bound() -> None:
    coordinator = ControlUserContentClearCoordinator(
        session_store=ControlSessionStore(),
        pending_permissions=PendingPermissionRegistry(),
        interaction_broker=InteractionBroker(),
    )

    with pytest.raises(
        RuntimeError,
        match="control transcript subscriber is not initialized",
    ):
        async with coordinator.user_content_clear_boundary():
            pass
