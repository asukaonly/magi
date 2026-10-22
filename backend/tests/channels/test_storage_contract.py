"""The channel domain behaves identically against real SQLite and MySQL."""

import asyncio
import os
from dataclasses import replace

import pytest
from sqlalchemy import text
from magi_plugin_sdk.delivery import DeliveryReceipt
from magi.channels.contracts import ChannelSessionMapping
from magi.channels.ports import ChannelRepositories
from magi.channels.persistence.session_mappings import SqliteChannelSessionRepository
from magi.channels.receipts_store import DeliveryReceiptsStore
from magi.channels.binding_settings_store import ChannelBindingSettingsStore
from magi.outreach.ports import OutreachRepositories
from magi.outreach.stores import OutreachOutboxStore, OutreachDeliveryLogStore
from magi.outreach.contracts import OutreachIntentConflictError
from magi.db.mysql import MysqlDatabase, MysqlSettings
from magi.db.mysql_migrations import upgrade_mysql_channels


@pytest.fixture(params=["sqlite", "mysql"])
async def repositories(request, tmp_path, ensure_db_schema, monkeypatch):
    if request.param == "sqlite":
        path = str(tmp_path / "channels.db")
        ensure_db_schema("channels", path)
        yield (
            ChannelRepositories(
                SqliteChannelSessionRepository(path),
                DeliveryReceiptsStore(db_path=path),
                ChannelBindingSettingsStore(db_path=path),
            ),
            OutreachRepositories(
                OutreachOutboxStore(db_path=path), OutreachDeliveryLogStore(db_path=path)
            ),
        )
        return
    port = os.environ.get("MAGI_TEST_MYSQL_PORT")
    if not port:
        pytest.skip("Set MAGI_TEST_MYSQL_PORT to test MySQL repositories")
    name = os.environ.get("MAGI_TEST_MYSQL_DATABASE", "magi_test_architecture")
    assert name.startswith("magi_test_"), (
        "Repository integration requires a disposable magi_test_ database"
    )
    monkeypatch.setenv("MAGI_MYSQL_TEST_PASSWORD", os.environ.get("MAGI_TEST_MYSQL_PASSWORD", ""))
    db = MysqlDatabase(
        MysqlSettings(
            host="127.0.0.1",
            port=int(port),
            database=name,
            user=os.environ.get("MAGI_TEST_MYSQL_USER", "root"),
            password_env="MAGI_MYSQL_TEST_PASSWORD",
            tls=False,
        )
    )
    from magi.channels.persistence.mysql import (
        MysqlChannelSessionRepository,
        MysqlDeliveryReceiptsRepository,
        MysqlChannelBindingSettingsRepository,
    )
    from magi.outreach.persistence.mysql import (
        MysqlOutreachOutboxRepository,
        MysqlOutreachDeliveryLogRepository,
    )

    try:
        await upgrade_mysql_channels(db)
        channels = ChannelRepositories(
            MysqlChannelSessionRepository(db),
            MysqlDeliveryReceiptsRepository(db),
            MysqlChannelBindingSettingsRepository(db),
        )
        outreach = OutreachRepositories(
            MysqlOutreachOutboxRepository(db), MysqlOutreachDeliveryLogRepository(db)
        )
        await channels.sessions.clear_conversation_state()
        async with db.transaction() as connection:
            await connection.execute(text("DELETE FROM channel_binding_settings"))
            await connection.execute(text("DELETE FROM channel_relay_state"))
        yield channels, outreach
    finally:
        await db.close()


def mapping(thread="one"):
    return ChannelSessionMapping(
        channel_type="channel.conn-a.telegram",
        external_chat_id="chat-1",
        external_thread_id=thread,
        magi_session_id="session-" + thread,
        magi_user_id="local_user",
        is_group=True,
        created_at_ms=1,
        last_active_at_ms=1,
        metadata_json='{"name":"中文"}',
    )


async def test_binding_identity_includes_connection_and_thread(repositories):
    channels, _ = repositories
    await channels.sessions.initialize()
    first = mapping()
    second = mapping("two")
    other_connection = replace(
        first, channel_type="channel.conn-b.telegram", magi_session_id="other"
    )
    unicode_long = replace(
        first,
        external_chat_id="设备" * 512,
        external_thread_id="主题" * 512,
        magi_session_id="long",
    )
    for item in (first, second, other_connection, unicode_long):
        await channels.sessions.insert(item)
        assert (
            await channels.sessions.lookup(
                item.channel_type, item.external_chat_id, external_thread_id=item.external_thread_id
            )
            == item
        )
    assert (
        await channels.sessions.lookup(
            first.channel_type, first.external_chat_id, external_thread_id="unknown"
        )
        is None
    )
    await channels.sessions.touch(
        first.channel_type, first.external_chat_id, 100, external_thread_id="one"
    )
    assert (
        await channels.sessions.lookup_by_session(first.magi_session_id)
    ).last_active_at_ms == 100
    await channels.sessions.delete_mapping(
        first.channel_type, first.external_chat_id, external_thread_id="one"
    )
    assert len(await channels.sessions.list_all()) == 3
    assert (
        await channels.sessions.lookup(
            second.channel_type, second.external_chat_id, external_thread_id="two"
        )
        == second
    )


async def test_preferences_default_to_denial_and_preserve_exact_identity(repositories):
    channels, _ = repositories
    repo = channels.binding_settings
    await repo.initialize()
    assert not (await repo.get(channel_type="a", external_user_id="user")).auto_approve
    assert await repo.list_all() == []
    await repo.set_auto_approve(channel_type="a", external_user_id="user", auto_approve=True)
    await repo.set_auto_approve(channel_type="a", external_user_id="USER", auto_approve=False)
    assert (await repo.get(channel_type="a", external_user_id="user")).auto_approve
    assert not (await repo.get(channel_type="b", external_user_id="user")).auto_approve
    assert not (await repo.get(channel_type="a", external_user_id="USER")).auto_approve
    assert len(await repo.list_all()) == 2


async def test_receipts_keep_each_revision_and_clear_exact_run(repositories):
    channels, _ = repositories
    await channels.receipts.initialize()
    first = DeliveryReceipt(
        channel_id="channel.conn-a.telegram",
        external_message_id="外部-1",
        delivered_at_ms=10,
        magi_session_id="session",
    )
    second = replace(first, external_message_id="外部-2")
    await channels.receipts.save_receipts(
        session_id="session", run_id="run", revision=1, receipts=[first]
    )
    await channels.receipts.save_receipts(
        session_id="session", run_id="run", revision=2, receipts=[second]
    )
    await channels.receipts.save_receipts(
        session_id="session", run_id="other", revision=1, receipts=[first]
    )
    assert await channels.receipts.list_receipts(session_id="session", run_id="run") == [
        first,
        second,
    ]
    assert await channels.receipts.list_receipts(
        session_id="session", run_id="run", revision=2
    ) == [second]
    await channels.receipts.clear_receipts(session_id="session", run_id="run")
    assert await channels.receipts.list_receipts(session_id="session", run_id="run") == []
    assert await channels.receipts.list_receipts(session_id="session", run_id="other") == [first]


async def test_outreach_admission_and_uncertainty_are_durable(repositories):
    _, outreach = repositories
    command = dict(
        correlation_id="event",
        channel_scope="channel.conn-a.telegram",
        intent_fingerprint="fingerprint",
        intent_json='{"text":"result"}',
        release_at_ms=5,
        created_at_ms=1,
    )
    outcomes = await asyncio.gather(*(outreach.outbox.enqueue(**command) for _ in range(8)))
    assert sum(result.created for result in outcomes) == 1
    assert len({result.row_id for result in outcomes}) == 1
    row_id = outcomes[0].row_id
    with pytest.raises(OutreachIntentConflictError):
        await outreach.outbox.enqueue(**(command | {"intent_json": "{}"}))
    assert await outreach.outbox.list_due(now_ms=4) == []
    assert len(await outreach.outbox.list_due(now_ms=5)) == 1
    assert await outreach.outbox.begin_delivery_attempt(row_id)
    assert not await outreach.outbox.begin_delivery_attempt(row_id)
    await outreach.outbox.mark_status(row_id, "uncertain")
    assert not await outreach.outbox.restore_pending_after_unattempted_delivery(
        row_id, intent_json=command["intent_json"]
    )
    assert await outreach.outbox.list_due(now_ms=100) == []
    assert (await outreach.outbox.enqueue(**command)).status == "uncertain"
    await outreach.delivery_log.record(
        correlation_id="event",
        user_id="local_user",
        channel_type="channel.conn-a.telegram",
        delivered_at_ms=10,
    )
    await outreach.delivery_log.record(
        correlation_id="event",
        user_id="local_user",
        channel_type="channel.conn-a.telegram",
        delivered_at_ms=11,
    )
    assert await outreach.delivery_log.was_delivered("event", "channel.conn-a.telegram")
    assert await outreach.delivery_log.count_for_user_since("local_user", 0) == 1
    assert await outreach.delivery_log.count_for_user_since("local_user", 11) == 0


async def test_full_clear_preserves_preferences_and_relay_watermark(repositories):
    channels, outreach = repositories
    await channels.sessions.insert(mapping())
    await channels.sessions.update_notification_cursor("a", "chat", 10)
    await channels.sessions.update_relay_cursor("relay", 100)
    await channels.binding_settings.set_auto_approve(
        channel_type="a", external_user_id="user", auto_approve=True
    )
    await outreach.outbox.enqueue(
        correlation_id="event",
        channel_scope="channel.a",
        intent_fingerprint="f",
        intent_json="{}",
        release_at_ms=1,
        created_at_ms=1,
    )
    counts = await channels.sessions.clear_conversation_state()
    assert counts["channel_session_mappings"] == 1
    assert counts["outreach_outbox"] == 1
    assert await channels.sessions.list_all() == []
    assert await channels.sessions.get_notification_cursor("a", "chat") == 0
    assert await channels.sessions.get_relay_cursor("relay") == 100
    assert (
        await channels.binding_settings.get(channel_type="a", external_user_id="user")
    ).auto_approve
