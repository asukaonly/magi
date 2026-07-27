import json
import pytest


class _FakeChatStore:
    def __init__(self) -> None:
        self.appended = []
        self.replaced = []
        self.bumped = []
        self._seq = 0

    async def next_sequence_no(self, *, session_id: str) -> int:
        self._seq += 1
        return self._seq

    async def append_message(self, record) -> None:
        self.appended.append(record)

    async def append_completion_message_once(self, record):
        self.appended.append(record)
        if record.replaces_message_id is not None:
            self.replaced.append(
                (record.replaces_message_id, record.message_id)
            )
        self.bumped.append(record.session_id)
        return record, True

    async def mark_message_replaced(self, *, message_id: str, replaced_by_message_id: str) -> None:
        self.replaced.append((message_id, replaced_by_message_id))

    async def bump_history_version(self, session_id: str) -> int:
        self.bumped.append(session_id)
        return len(self.bumped)


@pytest.mark.asyncio
async def test_persist_completion_message_writes_record():
    from magi.chat.task_agent.postprocess.background import persist_completion_message

    store = _FakeChatStore()
    result = await persist_completion_message(
        store,
        session_id="s1",
        user_id="u1",
        role="assistant",
        message_kind="assistant_final",
        body="All done — found 3 options.",
        payload={"background_task_id": "task_abc", "background_task_status": "succeeded"},
        turn_id="turn-1",
        pending_message_id="msg_pending",
        created_at_ms=1_700_000_000_000,
        message_id="msg_outreach_1",
        correlation_id="task_abc",
        identity_fingerprint="fingerprint-1",
    )
    assert result.record is not None
    assert result.created is True
    assert len(store.appended) == 1
    written = store.appended[0]
    assert written.session_id == "s1"
    assert written.user_id == "u1"
    assert written.role == "assistant"
    assert written.message_kind == "assistant_final"
    assert written.content_text == "All done — found 3 options."
    assert written.is_visible is True
    assert written.is_final is True
    assert written.replaces_message_id == "msg_pending"
    assert json.loads(written.payload_json)["background_task_id"] == "task_abc"
    assert store.replaced == [("msg_pending", written.message_id)]
    assert store.bumped == ["s1"]
    # Full record-shape snapshot — these fields are the most likely to silently
    # break if persist_completion_message is edited later.
    assert written.created_at_ms == 1_700_000_000_000
    assert written.sequence_no == 1  # first next_sequence_no() call
    assert written.turn_id == "turn-1"
    assert written.replaced_by_message_id is None


@pytest.mark.asyncio
async def test_persist_returns_none_without_store():
    from magi.chat.task_agent.postprocess.background import persist_completion_message
    result = await persist_completion_message(
        None, session_id="s1", user_id="u1", role="assistant",
        message_kind="assistant_final", body="x", payload={},
        turn_id=None,
        pending_message_id=None, created_at_ms=1,
        message_id="msg_outreach_1", correlation_id="task_abc",
        identity_fingerprint="fingerprint-1",
    )
    assert result.record is None
    assert result.created is False
