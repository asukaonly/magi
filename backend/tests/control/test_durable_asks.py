"""Questions survive inspection; only one valid device answer commits."""
import asyncio
import time

import pytest

from magi.control.ask_contracts import AskState
from magi.control.persistence.asks import SqliteAskRepository
from magi.control.session_store import ControlSessionStore
from magi.control.common import InteractionBroker


@pytest.fixture
def repository(tmp_path, ensure_db_schema):
    path = tmp_path / "runtime.db"
    ensure_db_schema("runtime_trace", path)
    return SqliteAskRepository(str(path)), path


@pytest.mark.asyncio
async def test_two_devices_race_with_one_durable_winner(repository):
    repo, path = repository
    await repo.open(session_id="session", ask=AskState("request", "Choose", options=("one", "two"), allow_free_text=False))
    second = SqliteAskRepository(str(path))
    answers = await asyncio.gather(repo.resolve(request_id="request", answer="one", now=time.time()), second.resolve(request_id="request", answer="two", now=time.time()))
    assert sum(answer is not None for answer in answers) == 1
    recovered = await repo.recover(now=time.time())
    assert recovered[0][1].answer == next(answer.answer for answer in answers if answer is not None)
    assert await repo.resolve(request_id="request", answer="one", now=time.time()) is None


@pytest.mark.asyncio
async def test_invalid_expired_or_replaced_question_rejects_answer(repository):
    repo, _ = repository
    now = time.time()
    await repo.open(session_id="session", ask=AskState("first", "Choose", options=("one",), allow_free_text=False, expires_at=now+5))
    assert await repo.resolve(request_id="first", answer="invalid", now=now) is None
    assert await repo.resolve(request_id="first", answer="one", now=now+6) is None
    await repo.open(session_id="session", ask=AskState("second", "New question"))
    assert await repo.resolve(request_id="first", answer="one", now=now) is None


@pytest.mark.asyncio
async def test_restart_closes_orphaned_questions_and_preserves_answer(repository):
    repo, path = repository
    first = ControlSessionStore(db_path=path)
    await first.initialize()
    question = await first.open_ask("session", question="Continue?", request_id="pending")
    second = ControlSessionStore(db_path=path)
    await second.initialize()
    assert second.ask_state("session").status == "cancelled"
    assert not await first.accept_ask_answer(question.request_id, "late")
    await second.open_ask("session", question="Another?", request_id="answered")
    assert await second.accept_ask_answer("answered", " yes ")
    third = ControlSessionStore(db_path=path)
    await third.initialize()
    assert third.ask_state("session").answer == "yes"
    assert third.ask_state("session").status == "answered"


@pytest.mark.asyncio
async def test_clear_removes_questions_and_rejects_stale_replies(repository):
    _, path = repository
    store = ControlSessionStore(db_path=path)
    await store.initialize()
    await store.open_ask("session", question="Sensitive", request_id="old")
    async with store.user_content_clear_boundary():
        assert store.ask_state("session") is None
    assert not await store.accept_ask_answer("old", "yes")
    restored = ControlSessionStore(db_path=path)
    await restored.initialize()
    assert restored.ask_state("session") is None


@pytest.mark.asyncio
async def test_broker_acknowledges_only_after_durable_commit(repository):
    _, path = repository
    store = ControlSessionStore(db_path=path)
    await store.initialize()
    await store.open_ask("session", question="Choose", options=["yes"], allow_free_text=False, request_id="r")
    broker = InteractionBroker()
    waiting = asyncio.create_task(broker.wait(interaction_id="r", kind="ask", timeout_seconds=5,
        before_resolve=lambda answer: store.accept_ask_answer("r", answer)))
    await asyncio.sleep(0)
    assert not await broker.resolve(interaction_id="r", kind="ask", response="wrong")
    assert not waiting.done()
    assert await broker.resolve(interaction_id="r", kind="ask", response="yes")
    assert store.ask_state("session").status == "answered"
    assert not await broker.resolve(interaction_id="r", kind="ask", response="yes")
    assert await waiting == "yes"
