"""A stale background computation cannot overwrite newer user or source evidence."""
import asyncio
import time

import pytest

from magi.core.sqlite import sqlite_connection_async


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["confirmation", "evidence"])
async def test_stale_reconcile_is_neither_written_nor_published(l2_store_with_schema, monkeypatch, mutation):
    store = l2_store_with_schema
    now = time.time()
    candidate = {
        "entity_id": "user:local_user", "entity_type": "user",
        "trait_name": "identity.preferred_name", "trait_family": "identity_profile",
        "trait_value": "River", "confidence_score": 0.5, "volatility_index": 0.2,
        "evidence_events": ["event-a"], "first_inferred_at": now - 1,
        "last_validated_at": now, "source_domain": "user_authored",
        "inference_depth": "direct", "temporal_scope": "stable",
    }
    assertion_id = await store.upsert_assertion_candidate(candidate)
    original = await store.get_tom_assertion(assertion_id=assertion_id)
    read_complete, resume_write = asyncio.Event(), asyncio.Event()
    original_write = store._write_reconciled_assertions

    async def delayed(writes):
        read_complete.set()
        await resume_write.wait()
        return await original_write(writes)

    monkeypatch.setattr(store, "_write_reconciled_assertions", delayed)
    task = asyncio.create_task(store.reconcile_entity(entity_id="user:local_user"))
    try:
        await asyncio.wait_for(read_complete.wait(), timeout=2)
        if mutation == "confirmation":
            await store.apply_user_feedback(assertion_id=assertion_id, feedback="confirmed")
        else:
            await store.upsert_assertion_candidate({**candidate, "evidence_events": ["event-b"]})
        # Simulate a coarse/frozen wall clock: timestamps alone are not revisions.
        async with sqlite_connection_async(store.db_path) as db:
            await db.execute("UPDATE tom_trait_assertions SET updated_at = ? WHERE assertion_id = ?", (original["updated_at"], assertion_id))
            await db.commit()
        authoritative = await store.get_tom_assertion(assertion_id=assertion_id)
        resume_write.set()
        assert await asyncio.wait_for(task, timeout=2) == []
        current = await store.get_tom_assertion(assertion_id=assertion_id)
        assert current == authoritative
        if mutation == "confirmation":
            assert current["validation_state"] == "stable"
            assert current["user_feedback"] == "confirmed"
        else:
            assert set(current["evidence_events"]) == {"event-a", "event-b"}
        # The next pass can publish an outcome computed from the new state.
        assert len(await store.reconcile_entity(entity_id="user:local_user")) == 1
    finally:
        resume_write.set()
        await asyncio.gather(task, return_exceptions=True)
