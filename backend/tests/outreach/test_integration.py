"""End-to-end integration test for the outreach layer.

Wires REAL: OutreachService + Governor + TargetResolver +
             DesktopTranscriptExecutor + ExternalChannelExecutor +
             real SQLite stores (OutreachOutboxStore, OutreachDeliveryLogStore).

Fakes only: chat store, chat read service, session mapper, channel router,
            and the compose step.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from magi_plugin_sdk.channels import ChannelTarget
from magi_plugin_sdk.delivery import DeliveryReceipt

from magi.outreach.contracts import OutreachIntent, OutreachKind, Urgency
from magi.outreach.governor import Governor
from magi.outreach.target_resolver import TargetResolver
from magi.outreach.executor import DesktopTranscriptExecutor, ExternalChannelExecutor
from magi.outreach.service import OutreachService
from magi.outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore


class _Store:
    def __init__(self): self.appended = []
    async def next_sequence_no(self, *, session_id): return 1
    async def append_message(self, record): self.appended.append(record)
    async def mark_message_replaced(self, **kw): pass
    async def bump_history_version(self, session_id): pass


class _ReadService:
    async def aget_session_summary(self, user_id, session_id):
        return SimpleNamespace(session_id=session_id)  # session valid


class _Mapper:
    def __init__(self, channel_type): self._c = channel_type
    async def lookup_by_session(self, sid):
        return SimpleNamespace(channel_type=self._c, external_chat_id="X1", magi_user_id="u1")


class _Router:
    def __init__(self): self.delivered = []
    async def fanout_deliver(self, *, content, targets):
        self.delivered.append((content.text, targets[0].channel_type))
        return [DeliveryReceipt(channel_id=targets[0].channel_type, external_message_id="m", delivered_at_ms=1)]


async def _say(intent): return f"[magi] {intent.facts}"


def _intent(urgency=Urgency.NORMAL, cid="c1"):
    return OutreachIntent(kind=OutreachKind.TASK_COMPLETED, user_id="u1", origin_session_id="s1",
                          title="t", facts="3 flights found", correlation_id=cid,
                          completed_at_ms=1, urgency=urgency)


def _build(runtime_paths, mapper, router, hour):
    import datetime as _dt
    db = str(runtime_paths.channels_db_path)
    svc = OutreachService(
        compose=_say,
        target_resolver=TargetResolver(read_service_factory=lambda: _ReadService(), session_mapper=mapper),
        governor=Governor(delivery_log=OutreachDeliveryLogStore(db_path=db),
                          now_local=lambda: _dt.datetime(2026, 6, 2, hour, 0, 0)),
        desktop_executor=DesktopTranscriptExecutor(chat_store=_Store()),
        external_executor=ExternalChannelExecutor(delivery_router=router, receipts_store=None),
        outbox=OutreachOutboxStore(db_path=db),
        delivery_log=OutreachDeliveryLogStore(db_path=db),
    )
    return svc


@pytest.mark.asyncio
async def test_external_origin_pushes_personified_to_channel(runtime_paths_with_schema):
    router = _Router()
    svc = _build(runtime_paths_with_schema, _Mapper("telegram"), router, hour=12)
    await svc.submit(_intent())
    assert router.delivered == [("[magi] 3 flights found", "telegram")]


@pytest.mark.asyncio
async def test_desktop_origin_does_not_push(runtime_paths_with_schema):
    router = _Router()
    svc = _build(runtime_paths_with_schema, _Mapper("chat_sse"), router, hour=12)
    await svc.submit(_intent())
    assert router.delivered == []


@pytest.mark.asyncio
async def test_quiet_hours_defers_then_drain_delivers(runtime_paths_with_schema):
    import datetime as _dt
    router = _Router()
    # Quiet hours (02:00) -> submit defers to outbox, no push.
    svc = _build(runtime_paths_with_schema, _Mapper("telegram"), router, hour=2)
    await svc.submit(_intent(cid="c2"))
    assert router.delivered == []
    # Swap governor to daytime and drain -> the deferred row delivers.
    svc._governor = Governor(
        delivery_log=OutreachDeliveryLogStore(db_path=str(runtime_paths_with_schema.channels_db_path)),
        now_local=lambda: _dt.datetime(2026, 6, 2, 12, 0, 0),
    )
    await svc.drain_due(now_ms=10**18)
    assert router.delivered == [("[magi] 3 flights found", "telegram")]
