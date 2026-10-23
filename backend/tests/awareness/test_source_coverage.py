"""Coverage is accepted with durable receipts, never with fetch or staging alone."""
import pytest
from magi_plugin_sdk import PluginConnection, SourceChange, SourceChangeBatch, SourceCoverage
from magi.awareness.source_store import SourceStore


@pytest.mark.asyncio
async def test_coverage_waits_for_receipts_and_survives_restart(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    connection = PluginConnection(connection_id="a", plugin_id="mail", display_name="a", enabled=True)
    checkpoint = await store.checkpoint(connection, "mail", "mail")
    change = SourceChange(object_id="one", version="one")
    coverage = SourceCoverage(checked_at=100, completeness="complete")
    batch = await store.stage_batch(connection, checkpoint, SourceChangeBatch(changes=[change], coverage=coverage))
    assert await store.coverage(connection, "mail") is None
    with pytest.raises(RuntimeError, match="unconfirmed"):
        await store.accept_batch(connection, batch)
    assert await store.coverage(connection, "mail") is None
    await store.record_receipt(batch, change, event_id="event", outcome="persisted")
    await store.accept_batch(connection, batch)
    assert await SourceStore(store.db_path).coverage(connection, "mail") == coverage


@pytest.mark.asyncio
async def test_empty_check_advances_freshness_partial_page_invalidates_and_clear_erases(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    connection = PluginConnection(connection_id="a", plugin_id="mail", display_name="a", enabled=True)
    for checked_at, complete in [(100, True), (200, True), (300, False)]:
        checkpoint = await store.checkpoint(connection, "mail", "mail")
        coverage = SourceCoverage(checked_at=checked_at, completeness="complete" if complete else "partial")
        pending = await store.stage_batch(connection, checkpoint, SourceChangeBatch(
            next_cursor=str(checked_at), complete=complete, coverage=coverage,
        ))
        await store.accept_batch(connection, pending)
        assert await store.coverage(connection, "mail") == coverage
    await store.clear_user_content()
    assert await store.coverage(connection, "mail") is None


@pytest.mark.asyncio
async def test_governed_skip_is_not_complete_local_coverage(tmp_path):
    store = SourceStore(tmp_path / "sources.db")
    connection = PluginConnection(connection_id="a", plugin_id="mail", display_name="a", enabled=True)
    checkpoint = await store.checkpoint(connection, "mail", "mail")
    change = SourceChange(object_id="forgotten", version="one")
    pending = await store.stage_batch(connection, checkpoint, SourceChangeBatch(
        changes=[change], coverage=SourceCoverage(checked_at=100, completeness="complete"),
    ))
    await store.record_receipt(pending, change, event_id="event", outcome="governed_skip")
    await store.accept_batch(connection, pending)
    coverage = await store.coverage(connection, "mail")
    assert coverage.completeness == "partial"
    assert "governed_omissions" in coverage.gaps
