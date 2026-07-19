import asyncio
import json
from pathlib import Path

import pytest
from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
)
from magi.delivery.contracts import (
    DeliveryFailure,
    DeliveryFanoutResult,
)
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryReceipt
from magi.chat.contracts import ChatMessageRecord, ChatSessionRecord
from magi.chat.store import ChatStore
from magi.outreach.contracts import (
    OutreachIntent,
    OutreachIntentConflictError,
    OutreachKind,
)
from magi.outreach.executor import (
    DesktopTranscriptExecutor,
    ExternalChannelDeliveryError,
    ExternalChannelExecutor,
)
from magi.outreach.producers.background_completion import task_to_intent


def _intent(kind=OutreachKind.TASK_COMPLETED):
    return OutreachIntent(kind=kind, user_id="u1", origin_session_id="s1",
                          title="t", facts="f", correlation_id="c1",
                          completed_at_ms=123, origin_turn_id="turn-1",
                          pending_message_id="pm1",
                          payload={"background_task_id": "c1"})


class _Store:
    def __init__(self): self.calls = []
    async def next_sequence_no(self, *, session_id): return 1
    async def append_completion_message_once(self, record):
        self.calls.append(("append", record))
        return record, True


class _Router:
    def __init__(
        self,
        *,
        fail: bool = False,
        delivery_attempted: bool = True,
    ):
        self.delivered = []
        self.fail = fail
        self.delivery_attempted = delivery_attempted

    async def fanout_deliver(self, *, content, targets):
        self.delivered.append((content, targets))
        if self.fail:
            return DeliveryFanoutResult(
                failures=(
                    DeliveryFailure(
                        target=targets[0],
                        error=RuntimeError("channel unavailable"),
                        delivery_attempted=self.delivery_attempted,
                    ),
                )
            )
        return DeliveryFanoutResult(
            receipts=(
                DeliveryReceipt(
                    channel_id=targets[0].channel_type,
                    external_message_id="m1",
                    delivered_at_ms=1,
                ),
            )
        )


class _Receipts:
    def __init__(self): self.saved = []
    async def save_receipts(self, *, session_id, run_id, revision, receipts):
        self.saved.append((session_id, run_id, revision, receipts))


@pytest.mark.asyncio
async def test_desktop_executor_writes_personified_body():
    store = _Store()
    ex = DesktopTranscriptExecutor(chat_store=store)
    rec = await ex.write(_intent(), body="搞定了！")
    assert rec is not None
    appended = [c for c in store.calls if c[0] == "append"][0][1]
    assert appended.role == "assistant"
    assert appended.message_kind == "assistant_final"
    assert appended.content_text == "搞定了！"
    assert appended.turn_id == "turn-1"


@pytest.mark.asyncio
async def test_desktop_executor_failed_uses_system_role():
    store = _Store()
    ex = DesktopTranscriptExecutor(chat_store=store)
    await ex.write(_intent(kind=OutreachKind.TASK_FAILED), body="炸了")
    appended = [c for c in store.calls if c[0] == "append"][0][1]
    assert appended.role == "system"
    assert appended.message_kind == "background_task_completion"


@pytest.mark.asyncio
async def test_external_executor_fans_out_and_saves_receipts():
    router, receipts = _Router(), _Receipts()
    ex = ExternalChannelExecutor(delivery_router=router, receipts_store=receipts)
    target = ChannelTarget(channel_type="telegram", external_chat_id="X1",
                           magi_session_id="s1", magi_user_id="u1")
    out = await ex.push(_intent(), body="hi", target=target)
    assert len(out) == 1
    assert router.delivered[0][0].text == "hi"
    assert receipts.saved[0][1] == "outreach:c1"


@pytest.mark.asyncio
async def test_external_executor_rejects_failed_delivery_without_saving_receipts():
    router, receipts = _Router(fail=True), _Receipts()
    ex = ExternalChannelExecutor(delivery_router=router, receipts_store=receipts)
    target = ChannelTarget(
        channel_type="telegram",
        external_chat_id="X1",
        magi_session_id="s1",
        magi_user_id="u1",
    )

    with pytest.raises(
        ExternalChannelDeliveryError,
        match="channel unavailable",
    ) as raised:
        await ex.push(_intent(), body="hi", target=target)

    assert raised.value.delivery_attempted is True
    assert receipts.saved == []


@pytest.mark.asyncio
async def test_external_executor_marks_lookup_failure_as_not_attempted():
    router = _Router(fail=True, delivery_attempted=False)
    ex = ExternalChannelExecutor(delivery_router=router, receipts_store=None)
    target = ChannelTarget(
        channel_type="telegram",
        external_chat_id="X1",
        magi_session_id="s1",
        magi_user_id="u1",
    )

    with pytest.raises(ExternalChannelDeliveryError) as raised:
        await ex.push(_intent(), body="hi", target=target)

    assert raised.value.delivery_attempted is False


async def _real_desktop_executor(runtime_paths_with_schema):
    store = ChatStore(
        db_path=str(runtime_paths_with_schema.chat_db_path),
        runtime_paths=runtime_paths_with_schema,
    )
    await store.upsert_session(
        ChatSessionRecord(
            session_id="s1",
            user_id="u1",
            title="Session",
            title_overridden=False,
            summary="",
            created_at_ms=1,
            updated_at_ms=1,
            last_message_at_ms=None,
            last_user_message_at_ms=None,
            last_message_preview="",
            last_user_message_preview="",
            message_count=0,
            archived_at_ms=None,
            deleted_at_ms=None,
        )
    )
    return store, DesktopTranscriptExecutor(chat_store=store)


@pytest.mark.asyncio
async def test_desktop_executor_concurrent_duplicate_keeps_one_original_row(
    runtime_paths_with_schema,
):
    store, executor = await _real_desktop_executor(runtime_paths_with_schema)
    intent = _intent()

    first, second = await asyncio.gather(
        executor.write(intent, body="Original result"),
        executor.write(intent, body="Original result"),
    )

    messages = await store.list_messages(session_id="s1")
    assert len(messages) == 1
    assert first.message_id == second.message_id == messages[0].message_id
    assert messages[0].content_text == "Original result"
    assert await store.get_history_version("s1") == 1


@pytest.mark.asyncio
async def test_desktop_executor_restart_reuses_exact_completion(
    runtime_paths_with_schema,
):
    store, executor = await _real_desktop_executor(runtime_paths_with_schema)
    first = await executor.write(_intent(), body="Original result")
    restarted = ChatStore(
        db_path=str(runtime_paths_with_schema.chat_db_path),
        runtime_paths=runtime_paths_with_schema,
    )

    second = await DesktopTranscriptExecutor(chat_store=restarted).write(
        _intent(),
        body="A newly rendered variation",
    )

    assert second.message_id == first.message_id
    assert second.content_text == "Original result"
    assert len(await restarted.list_messages(session_id="s1")) == 1
    assert await restarted.get_history_version("s1") == 1


@pytest.mark.asyncio
async def test_background_code_delegation_survives_into_chat_history(
    runtime_paths_with_schema,
):
    store, executor = await _real_desktop_executor(runtime_paths_with_schema)
    contract_path = (
        Path(__file__).resolve().parents[3]
        / "contracts"
        / "chat"
        / "code_agent_delegation_reference.json"
    )
    contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))[
        "payload"
    ]
    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id="u1",
            session_id="s1",
            origin_turn_id="turn-contract-code-agent",
            title="Change the code",
            goal="Implement the change",
            workspace_path="/workspace-at-execution",
        )
    )
    task.status = BackgroundTaskStatus.SUCCEEDED
    task.summary = "Done"
    task.finished_at = 1_700_000.0
    task.result_payload = {
        "message_payload": contract_payload,
    }
    intent = task_to_intent(task)
    assert intent is not None

    written = await executor.write(intent, body="The code change is ready.")

    assert written.turn_id == "turn-contract-code-agent"
    assert json.loads(written.payload_json)["code_agent_delegations"] == (
        contract_payload["code_agent_delegations"]
    )


@pytest.mark.asyncio
async def test_desktop_retry_attempt_can_follow_the_original_pending_result(
    runtime_paths_with_schema,
):
    store, executor = await _real_desktop_executor(runtime_paths_with_schema)
    await store.append_message(
        ChatMessageRecord(
            message_id="pm1",
            session_id="s1",
            turn_id=None,
            user_id="u1",
            role="system",
            message_kind="background_task_pending",
            content_text="Running",
            payload_json="{}",
            is_final=False,
            is_visible=True,
            created_at_ms=1,
            sequence_no=1,
            replaces_message_id=None,
            replaced_by_message_id=None,
        )
    )
    failed = OutreachIntent(
        kind=OutreachKind.TASK_FAILED,
        user_id="u1",
        origin_session_id="s1",
        title="Task",
        facts="Failed",
        correlation_id="task-1:attempt:0",
        completed_at_ms=2,
        pending_message_id="pm1",
    )
    succeeded = OutreachIntent(
        kind=OutreachKind.TASK_COMPLETED,
        user_id="u1",
        origin_session_id="s1",
        title="Task",
        facts="Done",
        correlation_id="task-1:attempt:1",
        completed_at_ms=3,
        pending_message_id=None,
    )

    failed_message = await executor.write(failed, body="First attempt failed")
    succeeded_message = await executor.write(succeeded, body="Retry succeeded")

    pending_message = await store.get_message("pm1")
    assert pending_message is not None
    assert pending_message.replaced_by_message_id == failed_message.message_id
    assert succeeded_message.message_id != failed_message.message_id
    assert succeeded_message.replaces_message_id is None
    assert [message.content_text for message in await store.list_messages(session_id="s1")] == [
        "Running",
        "First attempt failed",
        "Retry succeeded",
    ]


@pytest.mark.asyncio
async def test_desktop_executor_rejects_changed_intent_for_same_correlation(
    runtime_paths_with_schema,
):
    store, executor = await _real_desktop_executor(runtime_paths_with_schema)
    await executor.write(_intent(), body="Original result")
    conflicting = OutreachIntent(
        kind=OutreachKind.TASK_COMPLETED,
        user_id="u1",
        origin_session_id="s1",
        title="t",
        facts="different facts",
        correlation_id="c1",
        completed_at_ms=123,
        pending_message_id="pm1",
        payload={"background_task_id": "c1"},
    )

    with pytest.raises(
        OutreachIntentConflictError,
        match="different desktop content",
    ):
        await executor.write(conflicting, body="Changed result")

    messages = await store.list_messages(session_id="s1")
    assert len(messages) == 1
    assert messages[0].content_text == "Original result"
