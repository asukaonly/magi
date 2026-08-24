"""Golden parity test for the control-plane transcript projection inversion.

Control-Plane Extraction Phase 1. The control-actuator tools used to write
transcript rows by calling ``persist_*`` helpers in
``magi.control.chat_state_persister`` directly. That logic now lives in
the chat-side :class:`ControlTranscriptSubscriber`, driven by control
state-change events on the L3 bus.

The ``_GOLDEN`` records below were captured from the original
``chat_state_persister`` output (cross-checked field-by-field against the live
old implementation during the migration, including a deliberate-divergence
check proving the comparison is not a tautology). This test feeds the NEW
subscriber the corresponding control events and asserts the produced
``ChatMessageRecord`` rows + broadcast call sequences are byte-identical to the
golden for all five representative cases:

  * plan_state (enter then exit, replace-in-place)
  * todo_state (non-empty)
  * todo_state (empty -> hide latest)
  * ask_request
  * ask_response (which internally re-emits the request row)
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses

import aiosqlite
import pytest

from magi.chat import ChatSessionRecord, ChatStore, ChatTurnRecord
from magi.chat.storage.schema import CHAT_STORE_SCHEMA_SQL
from magi.core.container import get_container
from magi.events.domain_payloads import (
    AskSnapshot,
    ControlAskAnswered,
    ControlAskRequested,
    ControlPlanStateChanged,
    ControlTodoStateChanged,
)
from magi.events.events import (
    Event,
    EventTypes,
    PUBLISHED_MEMORY_EPOCH_METADATA_KEY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AskState:
    """Stand-in ask object; mirrors the control AskState the projector reads."""

    def __init__(self) -> None:
        self.request_id = "ask-1"
        self.question = "Proceed?"
        self.options = ("yes", "no")
        self.allow_free_text = True
        self.asked_at = 1.0
        self.timeout_seconds = 60.0
        self.expires_at = 61.0
        self.answered_at: float | None = None
        self.answer: str | None = None
        self.resolution: str | None = None

    @property
    def status(self) -> str:
        return "answered" if self.resolution == "user" else "pending"


def _ask_snapshot(ask: _AskState) -> AskSnapshot:
    return AskSnapshot(
        request_id=ask.request_id,
        question=ask.question,
        options=tuple(ask.options),
        allow_free_text=ask.allow_free_text,
        asked_at=ask.asked_at,
        timeout_seconds=ask.timeout_seconds,
        expires_at=ask.expires_at,
        answered_at=ask.answered_at,
        answer=ask.answer,
        resolution=ask.resolution,
        status=ask.status,
    )


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


async def _new_store(tmp_path) -> ChatStore:
    db_path = str(tmp_path / "chat.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(CHAT_STORE_SCHEMA_SQL)
        await db.commit()
    store = ChatStore(db_path=db_path)
    await store.initialize()
    await store.upsert_session(
        ChatSessionRecord(
            session_id="session-1",
            user_id="user-1",
            title="",
            title_overridden=False,
            summary="",
            created_at_ms=100,
            updated_at_ms=100,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    await store.upsert_turn(
        ChatTurnRecord(
            turn_id="turn-1",
            session_id="session-1",
            user_id="user-1",
            trace_id=None,
            orchestration_id=None,
            status="running",
            response_mode="final_only",
            execution_mode="orchestration",
            ux_plan_json="{}",
            created_at_ms=100,
            updated_at_ms=100,
            completed_at_ms=None,
            error_text=None,
        )
    )
    return store


def _make_id_normaliser():
    """Stable positional remapper for random ``msg_<uuid>`` ids.

    ``plan_state``/``todo_state`` rows use a random ``msg_<uuid>`` id (which
    also appears in neighbouring ``replaced_by_message_id`` fields and in the
    broadcast call lists), so we stabilise those ids positionally while leaving
    the deterministic ``ask:``/``ask-response:`` ids untouched. The same
    normaliser instance is applied to both rows and broadcast lists so equal
    underlying ids map to the same token.
    """
    id_map: dict[str, str] = {}

    def _map_id(value):
        if value is None:
            return None
        if value.startswith("msg_"):
            return id_map.setdefault(value, f"__msg_{len(id_map)}__")
        return value

    return _map_id


def _normalise_rows(rows, map_id):
    out = []
    for row in rows:
        d = dataclasses.asdict(row)
        d["message_id"] = map_id(d["message_id"])
        d["replaces_message_id"] = map_id(d["replaces_message_id"])
        d["replaced_by_message_id"] = map_id(d["replaced_by_message_id"])
        if d.get("reply_to_message_id"):
            d["reply_to_message_id"] = map_id(d["reply_to_message_id"])
        out.append(d)
    return out


def _patch_broadcasts(monkeypatch, upserts: list[str], hidden: list[str]) -> None:
    async def _upsert(**kwargs):
        upserts.append(str(kwargs["message_id"]))

    async def _hidden(**kwargs):
        hidden.append(str(kwargs["message_id"]))

    monkeypatch.setattr(
        "magi.chat.control_transcript_subscriber.broadcast_chat_message_upsert", _upsert
    )
    monkeypatch.setattr(
        "magi.chat.control_transcript_subscriber.broadcast_chat_message_hidden", _hidden
    )


def _row(**overrides):
    """Construct an expected row dict with the shared transcript defaults."""
    base = {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "user_id": "user-1",
        "role": "assistant",
        "content_text": None,
        "is_final": True,
        "is_visible": True,
        "replaces_message_id": None,
        "replaced_by_message_id": None,
        "persona_id": None,
        "reply_to_message_id": None,
        "label": None,
    }
    base.update(overrides)
    return base


class _FakeBus:
    async def subscribe(self, *_a, **_k):  # pragma: no cover - unused here
        return "sub"

    async def unsubscribe(self, *_a, **_k):  # pragma: no cover - unused here
        return True


async def _run(sub, event_type, payload):
    handler = {
        EventTypes.CONTROL_PLAN_STATE_CHANGED: sub._on_plan_state_changed,
        EventTypes.CONTROL_TODO_STATE_CHANGED: sub._on_todo_state_changed,
        EventTypes.CONTROL_ASK_REQUESTED: sub._on_ask_requested,
        EventTypes.CONTROL_ASK_ANSWERED: sub._on_ask_answered,
    }[event_type]
    await handler(Event(type=event_type, data=payload))
    await sub.drain()


# ---------------------------------------------------------------------------
# Parity cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_state_parity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_PLAN_STATE_CHANGED,
            ControlPlanStateChanged(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                state={"active": True, "plan_text": None, "entered_at": 1.0},
            ),
        )
        await _run(
            sub,
            EventTypes.CONTROL_PLAN_STATE_CHANGED,
            ControlPlanStateChanged(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                state={"active": False, "plan_text": "1. Inspect\n2. Ship", "entered_at": 1.0},
            ),
        )

    nmap = _make_id_normaliser()
    rows = _normalise_rows(await store.list_messages(session_id="session-1"), nmap)
    golden = [
        _row(
            message_id="__msg_0__",
            message_kind="plan_state",
            content_text=None,
            payload_json='{"active": true, "plan_text": null, "entered_at_ms": 1000, "exited_at_ms": null}',
            created_at_ms=1000,
            sequence_no=1,
            replaced_by_message_id="__msg_1__",
        ),
        _row(
            message_id="__msg_1__",
            message_kind="plan_state",
            content_text="1. Inspect\n2. Ship",
            payload_json='{"active": false, "plan_text": "1. Inspect\\n2. Ship", "entered_at_ms": 1000, "exited_at_ms": 1000}',
            created_at_ms=1000,
            sequence_no=2,
            replaces_message_id="__msg_0__",
        ),
    ]
    assert rows == golden
    assert [nmap(x) for x in up] == ["__msg_0__", "__msg_1__"]
    assert [nmap(x) for x in hi] == ["__msg_0__"]

    await store.shutdown()


@pytest.mark.asyncio
async def test_todo_state_nonempty_parity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    items = [
        {"id": "todo-1", "content": "Inspect runtime drift", "status": "in_progress",
         "created_at_ms": 1, "updated_at_ms": 2},
        {"id": "todo-2", "content": "Ship fix", "status": "pending",
         "created_at_ms": 1, "updated_at_ms": 3},
    ]

    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_TODO_STATE_CHANGED,
            ControlTodoStateChanged(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                plan={"plan_id": "plan-1", "items": items},
            ),
        )

    nmap = _make_id_normaliser()
    rows = _normalise_rows(await store.list_messages(session_id="session-1"), nmap)
    golden = [
        _row(
            message_id="__msg_0__",
            message_kind="todo_state",
            content_text="Inspect runtime drift\nShip fix",
            payload_json=(
                '{"items": [{"id": "todo-1", "content": "Inspect runtime drift", '
                '"status": "in_progress", "created_at_ms": 1, "updated_at_ms": 2}, '
                '{"id": "todo-2", "content": "Ship fix", "status": "pending", '
                '"created_at_ms": 1, "updated_at_ms": 3}], "orchestration_id": null}'
            ),
            created_at_ms=3000,
            sequence_no=1,
        ),
    ]
    assert rows == golden
    assert [nmap(x) for x in up] == ["__msg_0__"]
    assert hi == []

    await store.shutdown()


@pytest.mark.asyncio
async def test_todo_state_empty_hides_parity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    items = [
        {"id": "todo-1", "content": "Inspect runtime drift", "status": "in_progress",
         "created_at_ms": 1, "updated_at_ms": 2},
    ]

    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_TODO_STATE_CHANGED,
            ControlTodoStateChanged(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                plan={"plan_id": "plan-1", "items": items},
            ),
        )
        await _run(
            sub,
            EventTypes.CONTROL_TODO_STATE_CHANGED,
            ControlTodoStateChanged(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                plan={"plan_id": "plan-1", "items": []},
            ),
        )

    nmap = _make_id_normaliser()
    rows = _normalise_rows(await store.list_messages(session_id="session-1"), nmap)
    # Empty list hides the single existing row in place (no new row appended).
    golden = [
        _row(
            message_id="__msg_0__",
            message_kind="todo_state",
            content_text="Inspect runtime drift",
            payload_json=(
                '{"items": [{"id": "todo-1", "content": "Inspect runtime drift", '
                '"status": "in_progress", "created_at_ms": 1, "updated_at_ms": 2}], '
                '"orchestration_id": null}'
            ),
            created_at_ms=2000,
            sequence_no=1,
            is_visible=False,
        ),
    ]
    assert rows == golden
    assert [nmap(x) for x in up] == ["__msg_0__"]
    assert [nmap(x) for x in hi] == ["__msg_0__"]

    await store.shutdown()


@pytest.mark.asyncio
async def test_ask_request_parity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    ask = _AskState()
    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_ASK_REQUESTED,
            ControlAskRequested(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                ask=_ask_snapshot(ask), background=True,
            ),
        )

    nmap = _make_id_normaliser()
    rows = _normalise_rows(await store.list_messages(session_id="session-1"), nmap)
    golden = [
        _row(
            message_id="ask:ask-1",
            message_kind="ask_request",
            content_text="Proceed?",
            payload_json=(
                '{"ask_request_id": "ask-1", "session_id": "session-1", "status": "pending", '
                '"question": "Proceed?", "options": ["yes", "no"], "allow_free_text": true, '
                '"timeout_seconds": 60.0, "created_at_ms": 1000, "expires_at_ms": 61000, '
                '"answered_at_ms": null, "answer": null, "resolution": null, "background": true}'
            ),
            created_at_ms=1000,
            sequence_no=1,
        ),
    ]
    assert rows == golden
    assert up == ["ask:ask-1"]
    assert hi == []

    await store.shutdown()


@pytest.mark.asyncio
async def test_ask_response_parity(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    ask = _AskState()
    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_ASK_REQUESTED,
            ControlAskRequested(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                ask=_ask_snapshot(ask),
            ),
        )
        ask.answer = "yes"
        ask.resolution = "user"
        ask.answered_at = 2.0
        await _run(
            sub,
            EventTypes.CONTROL_ASK_ANSWERED,
            ControlAskAnswered(
                session_id="session-1", user_id="user-1", turn_id="turn-1",
                ask=_ask_snapshot(ask), answer="yes",
            ),
        )

    nmap = _make_id_normaliser()
    rows = _normalise_rows(await store.list_messages(session_id="session-1"), nmap)
    golden = [
        _row(
            message_id="ask:ask-1",
            message_kind="ask_request",
            content_text="Proceed?",
            payload_json=(
                '{"ask_request_id": "ask-1", "session_id": "session-1", "status": "answered", '
                '"question": "Proceed?", "options": ["yes", "no"], "allow_free_text": true, '
                '"timeout_seconds": 60.0, "created_at_ms": 1000, "expires_at_ms": 61000, '
                '"answered_at_ms": 2000, "answer": "yes", "resolution": "user", "background": false}'
            ),
            created_at_ms=1000,
            sequence_no=1,
        ),
        _row(
            message_id="ask-response:ask-1",
            role="user",
            message_kind="ask_response",
            content_text="yes",
            payload_json=(
                '{"ask_request_id": "ask-1", "session_id": "session-1", '
                '"answer": "yes", "answered_at_ms": 2000}'
            ),
            created_at_ms=2000,
            sequence_no=2,
            reply_to_message_id="ask:ask-1",
        ),
    ]
    assert rows == golden
    # The answer path re-emits the request row (status flips to "answered")
    # before writing the response row — hence the doubled request upsert.
    assert up == ["ask:ask-1", "ask:ask-1", "ask-response:ask-1"]
    assert hi == []

    await store.shutdown()


@pytest.mark.asyncio
async def test_answered_ask_does_not_recreate_deleted_request(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    store = await _new_store(tmp_path)
    up: list[str] = []
    hi: list[str] = []
    _patch_broadcasts(monkeypatch, up, hi)

    ask = _AskState()
    sub = ControlTranscriptSubscriber(event_bus=_FakeBus())
    with _override(chat_store=store):
        await _run(
            sub,
            EventTypes.CONTROL_ASK_REQUESTED,
            ControlAskRequested(
                session_id="session-1",
                user_id="user-1",
                turn_id="turn-1",
                ask=_ask_snapshot(ask),
            ),
        )
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                """
                INSERT INTO chat_cleared_message_scopes(
                    session_id, message_id, cleared_at_ms
                ) VALUES ('session-1', 'ask:ask-1', 1500)
                """
            )
            await db.execute(
                "DELETE FROM chat_messages WHERE message_id = 'ask:ask-1'"
            )
            await db.commit()

        ask.answer = "yes"
        ask.resolution = "user"
        ask.answered_at = 2.0
        await _run(
            sub,
            EventTypes.CONTROL_ASK_ANSWERED,
            ControlAskAnswered(
                session_id="session-1",
                user_id="user-1",
                turn_id="turn-1",
                ask=_ask_snapshot(ask),
                answer="yes",
            ),
        )

    assert await store.list_messages(session_id="session-1") == []
    assert up == ["ask:ask-1"]
    assert hi == []
    await store.shutdown()


@pytest.mark.asyncio
async def test_full_clear_drains_active_projection_and_discards_old_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from magi.chat.control_transcript_subscriber import ControlTranscriptSubscriber

    memory_epoch = 0
    active_started = asyncio.Event()
    release_active = asyncio.Event()
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()
    projected: list[str] = []

    sub = ControlTranscriptSubscriber(
        event_bus=_FakeBus(),
        memory_epoch_getter=lambda: memory_epoch,
    )

    async def project(payload: ControlPlanStateChanged) -> None:
        plan_text = str(payload.state.get("plan_text") or "")
        if plan_text == "active":
            active_started.set()
            await release_active.wait()
        projected.append(plan_text)

    monkeypatch.setattr(sub, "_project_plan_state", project)

    def event(plan_text: str, *, epoch: int) -> Event:
        return Event(
            type=EventTypes.CONTROL_PLAN_STATE_CHANGED,
            data=ControlPlanStateChanged(
                session_id="session-1",
                user_id="user-1",
                turn_id="turn-1",
                state={"active": False, "plan_text": plan_text},
            ),
            metadata={PUBLISHED_MEMORY_EPOCH_METADATA_KEY: epoch},
        )

    await sub._on_plan_state_changed(event("active", epoch=0))
    await asyncio.wait_for(active_started.wait(), timeout=1)
    await sub._on_plan_state_changed(event("queued-old", epoch=0))
    old_timestamp_event = event("old-timestamp", epoch=1)

    async def clear() -> None:
        async with sub.user_content_clear_boundary():
            clear_entered.set()
            await release_clear.wait()

    clear_task = asyncio.create_task(clear())
    await asyncio.sleep(0)
    assert clear_entered.is_set() is False
    await sub._on_plan_state_changed(event("during-clear", epoch=0))

    release_active.set()
    await asyncio.wait_for(clear_entered.wait(), timeout=1)
    memory_epoch = 1
    release_clear.set()
    await clear_task
    await sub.drain()

    await sub._on_plan_state_changed(event("stale-epoch", epoch=0))
    await sub._on_plan_state_changed(old_timestamp_event)
    await sub._on_plan_state_changed(event("fresh", epoch=1))
    await sub.drain()

    assert projected == ["active", "fresh"]
