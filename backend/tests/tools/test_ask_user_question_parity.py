"""Golden parity test for ``ask_user_question`` — Phase 4 Task 1.

Pins the *observable behavior* of the ask flow across the migration from
direct ``magi.control.*`` calls to the SDK ``InteractionPort``
capability (``ctx.capabilities.interaction.ask(...)``).

For each of the three resolution paths (answered / cancelled / timeout)
this records, against fakes/spies:

  * the resulting :class:`ToolResult` (success, data, error, error_code), and
  * the *exact ordered sequence* of control calls and events:
      - ``open_ask(resolution=…)`` via the real ``ControlSessionStore``
      - ``publish_control_ask_requested`` / ``publish_control_ask_answered``
        (the Phase-1 transcript events, with the ``background`` flag and the
        ask ``status``/``resolution`` at emit time)
      - ``publish_control_event`` channels (the UI notifications)
      - ``close_ask`` resolutions
      - background manager ``suspend``/``resume`` transitions

The same test body runs against the live tool; after the migration the tool
routes through the host ``InteractionPort`` adapter, which MUST reproduce the
identical sequence. The golden lives in the assertions below.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from magi.control.common import InteractionTimeoutError
from magi.control.session_store import ControlSessionStore
from magi.tools.builtin.ask_user_question_tool import AskUserQuestionTool
from magi.tools.schema import ToolExecutionContext
from magi_plugin_sdk.capabilities import ToolCapabilities

import magi.control.common.events as control_events
import magi.control.provider as control_provider
import magi.bootstrap.tool_capabilities as bootstrap_caps


# ---------------------------------------------------------------------------
# Spies / fakes
# ---------------------------------------------------------------------------


class _Trace:
    """Ordered log of every control call/event observed during a run."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, name: str, **fields: Any) -> None:
        self.events.append((name, fields))

    def names(self) -> list[str]:
        return [name for name, _ in self.events]


class _ImmediateAnswerBroker:
    """Broker stub that returns a fixed answer once a waiter enters."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    def user_content_generation(self) -> int:
        return 0

    async def wait(
        self,
        *,
        interaction_id: str,
        kind: str,
        timeout_seconds: float,
        metadata: dict[str, Any] | None = None,
        expected_generation: int | None = None,
    ) -> Any:
        # Yield once so the rest of the open/suspend flow runs before we
        # resolve, mirroring a real out-of-band resolution.
        await asyncio.sleep(0)
        return self._answer


class _TimeoutBroker:
    def user_content_generation(self) -> int:
        return 0

    async def wait(
        self,
        *,
        interaction_id: str,
        kind: str,
        timeout_seconds: float,
        metadata: dict[str, Any] | None = None,
        expected_generation: int | None = None,
    ) -> Any:
        await asyncio.sleep(0)
        raise InteractionTimeoutError(interaction_id, kind=kind)


class _NeverBroker:
    def user_content_generation(self) -> int:
        return 0

    async def wait(
        self,
        *,
        interaction_id: str,
        kind: str,
        timeout_seconds: float,
        metadata: dict[str, Any] | None = None,
        expected_generation: int | None = None,
    ) -> Any:
        await asyncio.Event().wait()


class _RecordingManager:
    def __init__(self, trace: _Trace) -> None:
        self._trace = trace

    async def suspend_waiting_user(self, task_id: str, *, reason: str = "awaiting_user_answer") -> bool:
        self._trace.record("manager.suspend", task_id=task_id, reason=reason)
        return True

    async def resume_from_wait(self, task_id: str) -> bool:
        self._trace.record("manager.resume", task_id=task_id)
        return True


class _Cancellation:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self.reason: str | None = None

    def cancel(self, reason: str) -> None:
        self.reason = reason
        self._event.set()

    async def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


def _install_spies(monkeypatch: pytest.MonkeyPatch, trace: _Trace, store: ControlSessionStore, broker: Any) -> None:
    """Patch the control surface so both the pre- and post-migration code paths
    are observed.

    Pre-migration the tool binds the control helpers into its own module
    namespace at import time and resolves the store/broker via the
    ``agent.control`` shims; post-migration the host ``InteractionPort`` adapter
    reaches the canonical ``magi.control.*`` module instead. We therefore patch
    *both* surfaces — the tool module (when the names still exist) and the
    canonical module — so the recorded sequence is identical either way.
    """

    real_open_ask = store.open_ask
    real_close_ask = store.close_ask

    async def _spy_open_ask(session_id: str, **kwargs: Any):
        ask = await real_open_ask(session_id, **kwargs)
        trace.record("open_ask", session_id=session_id, request_id=ask.request_id)
        return ask

    async def _spy_close_ask(
        session_id: str,
        *,
        request_id: str,
        expected_generation: int,
        answer: str | None,
        resolution: str,
    ):
        ask = await real_close_ask(
            session_id,
            request_id=request_id,
            expected_generation=expected_generation,
            answer=answer,
            resolution=resolution,
        )
        trace.record("close_ask", session_id=session_id, answer=answer, resolution=resolution)
        return ask

    monkeypatch.setattr(store, "open_ask", _spy_open_ask, raising=True)
    monkeypatch.setattr(store, "close_ask", _spy_close_ask, raising=True)

    async def _spy_ask_requested(*, session_id, user_id, turn_id, ask, background=False):
        trace.record(
            "ask_requested",
            session_id=session_id,
            background=background,
            status=getattr(ask, "status", None),
            resolution=getattr(ask, "resolution", None),
        )

    async def _spy_ask_answered(*, session_id, user_id, turn_id, ask, answer, background=False):
        trace.record(
            "ask_answered",
            session_id=session_id,
            answer=answer,
            background=background,
            status=getattr(ask, "status", None),
        )

    async def _spy_control_event(channel, payload, *, session_id=None, user_id=None, turn_id=None):
        trace.record("control_event", channel=channel)

    # Canonical module surface (post-migration: reached by the host adapter).
    monkeypatch.setattr(control_provider, "resolve_control_session_store", lambda: store, raising=True)
    monkeypatch.setattr(control_provider, "resolve_control_interaction_broker", lambda: broker, raising=True)
    monkeypatch.setattr(control_events, "publish_control_ask_requested", _spy_ask_requested, raising=True)
    monkeypatch.setattr(control_events, "publish_control_ask_answered", _spy_ask_answered, raising=True)
    monkeypatch.setattr(control_events, "publish_control_event", _spy_control_event, raising=True)

    # Pre-migration tool-module surface (names bound at import; gone afterward).
    from magi.tools.builtin import ask_user_question_tool as ask_module

    for attr, value in (
        ("resolve_control_session_store", lambda: store),
        ("resolve_control_interaction_broker", lambda: broker),
        ("publish_control_ask_requested", _spy_ask_requested),
        ("publish_control_ask_answered", _spy_ask_answered),
        ("publish_control_event", _spy_control_event),
    ):
        if hasattr(ask_module, attr):
            monkeypatch.setattr(ask_module, attr, value, raising=False)


def _make_ctx(trace: _Trace, *, background: bool) -> ToolExecutionContext:
    """Build a context wired with the host InteractionPort + a spy background
    manager, exactly as the production composition root would (minus the
    network/runtime singletons, which the spies stand in for)."""

    caps_kwargs: dict[str, Any] = {}
    # The migration adds ``interaction`` to the host capability bundle; until
    # then ``getattr`` yields None and the tool still drives control directly.
    interaction_port = getattr(bootstrap_caps, "_HostInteractionPort", None)
    if interaction_port is not None:
        caps_kwargs["interaction"] = interaction_port()
    if background:
        caps_kwargs["background"] = _RecordingManager(trace)

    if background:
        agent_id = "background:bg_99"
        env = {"session_id": "sess", "intent": "background", "turn_id": "turn"}
        features = ["allow_ask_in_background"]
    else:
        agent_id = "chat"
        env = {"session_id": "sess", "intent": "chat", "turn_id": "turn"}
        features = []

    return ToolExecutionContext(
        agent_id=agent_id,
        env_vars=env,
        permissions=[],
        enabled_features=features,
        capabilities=ToolCapabilities(**caps_kwargs),
    )


# ---------------------------------------------------------------------------
# Golden parity cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_answered_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _Trace()
    store = ControlSessionStore()
    _install_spies(monkeypatch, trace, store, _ImmediateAnswerBroker("the answer"))

    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "options": ["yes", "no"], "timeout_seconds": 30},
        _make_ctx(trace, background=False),
    )

    assert result.success is True
    assert result.data == {"answer": "the answer"}
    assert result.error is None

    assert trace.names() == [
        "open_ask",
        "ask_requested",
        "control_event",  # control.ask.requested UI notification
        "close_ask",
        "ask_answered",
    ]
    open_ask = trace.events[0][1]
    assert open_ask["session_id"] == "sess"
    assert trace.events[1][1]["background"] is False
    assert trace.events[2][1]["channel"] == "control.ask.requested"
    assert trace.events[3][1] == {
        "session_id": "sess",
        "answer": "the answer",
        "resolution": "user",
    }
    assert trace.events[4][1]["answer"] == "the answer"
    assert trace.events[4][1]["status"] == "answered"


@pytest.mark.asyncio
async def test_parity_timeout_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _Trace()
    store = ControlSessionStore()
    _install_spies(monkeypatch, trace, store, _TimeoutBroker())

    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "timeout_seconds": 5},
        _make_ctx(trace, background=False),
    )

    assert result.success is False
    assert result.data is None
    assert "no answer within 5s" in (result.error or "")

    assert trace.names() == [
        "open_ask",
        "ask_requested",
        "control_event",  # control.ask.requested UI notification
        "close_ask",
        "ask_requested",  # re-emit closed ask so transcript reflects timeout
    ]
    assert trace.events[3][1] == {
        "session_id": "sess",
        "answer": None,
        "resolution": "timeout",
    }
    # The re-emitted request carries the resolved (timeout) ask snapshot.
    assert trace.events[4][1]["resolution"] == "timeout"
    assert trace.events[4][1]["status"] == "timeout"


@pytest.mark.asyncio
async def test_parity_cancelled_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _Trace()
    store = ControlSessionStore()
    _install_spies(monkeypatch, trace, store, _NeverBroker())

    cancellation = _Cancellation()
    ctx = _make_ctx(trace, background=False)
    ctx.cancellation = cancellation

    async def cancel_soon() -> None:
        # Let the tool open the ask and enter the wait first.
        for _ in range(50):
            if store.ask_state("sess") is not None:
                cancellation.cancel("test_cancel")
                return
            await asyncio.sleep(0.005)

    asyncio.create_task(cancel_soon())
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "timeout_seconds": 30},
        ctx,
    )

    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert result.error == "run cancelled before answer"

    assert trace.names() == [
        "open_ask",
        "ask_requested",
        "control_event",  # control.ask.requested UI notification
        "close_ask",
        "ask_requested",  # re-emit closed ask so transcript reflects cancel
    ]
    assert trace.events[3][1] == {
        "session_id": "sess",
        "answer": None,
        "resolution": "cancelled",
    }
    assert trace.events[4][1]["resolution"] == "cancelled"
    assert trace.events[4][1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_parity_answered_background(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _Trace()
    store = ControlSessionStore()
    _install_spies(monkeypatch, trace, store, _ImmediateAnswerBroker("bg-answer"))

    result = await AskUserQuestionTool().execute(
        {"question": "Continue?", "timeout_seconds": 30},
        _make_ctx(trace, background=True),
    )

    assert result.success is True
    assert result.data == {"answer": "bg-answer"}

    # Background path: suspend after ask_requested, two UI events
    # (control.ask.requested + control.background.suspended); on answer the
    # ask is closed + the answered transcript event emitted, THEN the task is
    # resumed and a final control.background.resumed event is published.
    assert trace.names() == [
        "open_ask",
        "ask_requested",
        "manager.suspend",
        "control_event",  # control.ask.requested
        "control_event",  # control.background.suspended
        "close_ask",
        "ask_answered",
        "manager.resume",
        "control_event",  # control.background.resumed
    ]
    assert trace.events[1][1]["background"] is True
    assert trace.events[2][1] == {"task_id": "bg_99", "reason": "awaiting_user_answer"}
    assert trace.events[3][1]["channel"] == "control.ask.requested"
    assert trace.events[4][1]["channel"] == "control.background.suspended"
    assert trace.events[5][1]["resolution"] == "user"
    assert trace.events[6][1]["background"] is True
    assert trace.events[6][1]["answer"] == "bg-answer"
    assert trace.events[7][1] == {"task_id": "bg_99"}
    assert trace.events[8][1]["channel"] == "control.background.resumed"


@pytest.mark.asyncio
async def test_parity_timeout_background(monkeypatch: pytest.MonkeyPatch) -> None:
    trace = _Trace()
    store = ControlSessionStore()
    _install_spies(monkeypatch, trace, store, _TimeoutBroker())

    result = await AskUserQuestionTool().execute(
        {"question": "Continue?", "timeout_seconds": 1},
        _make_ctx(trace, background=True),
    )

    assert result.success is False
    assert "no answer within 1s" in (result.error or "")

    assert trace.names() == [
        "open_ask",
        "ask_requested",
        "manager.suspend",
        "control_event",  # control.ask.requested
        "control_event",  # control.background.suspended
        "close_ask",
        "ask_requested",  # re-emit closed (timeout) ask
        "manager.resume",
    ]
    assert trace.events[2][1]["task_id"] == "bg_99"
    assert trace.events[5][1]["resolution"] == "timeout"
    assert trace.events[6][1]["resolution"] == "timeout"
    assert trace.events[7][1] == {"task_id": "bg_99"}
