import pytest
from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryReceipt
from magi.outreach.contracts import OutreachIntent, OutreachKind
from magi.outreach.executor import DesktopTranscriptExecutor, ExternalChannelExecutor


def _intent(kind=OutreachKind.TASK_COMPLETED):
    return OutreachIntent(kind=kind, user_id="u1", origin_session_id="s1",
                          title="t", facts="f", correlation_id="c1",
                          completed_at_ms=123, pending_message_id="pm1",
                          payload={"background_task_id": "c1"})


class _Store:
    def __init__(self): self.calls = []
    async def next_sequence_no(self, *, session_id): return 1
    async def append_message(self, record): self.calls.append(("append", record))
    async def mark_message_replaced(self, *, message_id, replaced_by_message_id):
        self.calls.append(("replace", message_id))
    async def bump_history_version(self, session_id): self.calls.append(("bump", session_id))


class _Router:
    def __init__(self): self.delivered = []
    async def fanout_deliver(self, *, content, targets):
        self.delivered.append((content, targets))
        return [DeliveryReceipt(channel_id=targets[0].channel_type, external_message_id="m1", delivered_at_ms=1)]


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
