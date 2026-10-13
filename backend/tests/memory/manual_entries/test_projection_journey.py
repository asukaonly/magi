"""User-authored facts traverse durable handoff, recovery and self projection."""
from __future__ import annotations

import asyncio
import time

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.manual_entries import (
    ManualEntry, ManualEntryStore, ManualEntryL1Projector,
    ManualEntryWorkflow, ManualEntryRecoveryService,
)
from ..l2.test_claim_text_pipeline import _open_store, _response


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_missing_identity", [False, True])
async def test_manual_fact_reaches_self_portrait_and_recovery_is_idempotent(
    tmp_path, repair_missing_identity,
):
    memory, adapter = await _open_store(tmp_path, '{}')
    try:
        entries = ManualEntryStore(db_path=memory.memory_db_path)
        projector = ManualEntryL1Projector(memory=memory)
        workflow = ManualEntryWorkflow(store=entries, projector=projector, memory=memory)
        entry = ManualEntry(entry_id='manual-self-name', created_at=time.time(),
                            event_at=time.time(), body='我叫明日香')
        await entries.create(entry)
        if repair_missing_identity:
            await workflow.project_and_link(entry=entry, predecessor_event_id=None)
            original_id = entry.l1_event_id
            async with sqlite_connection_async(memory.l1_db_path) as db:
                await db.execute('UPDATE fact_events SET user_id = NULL WHERE event_id = ?', (original_id,))
                await db.commit()
            expected_id = projector.event_id_for(entry, predecessor_event_id=original_id)
        else:
            original_id = None
            expected_id = projector.event_id_for(entry, predecessor_event_id=None)
        adapter._responses = [_response(event_id=expected_id, object_ref='明日香',
            evidence=entry.body, entities=[], predicate='REAL_NAME',
            object_type='person', fact_kind='explicit_fact')]
        recovery = ManualEntryRecoveryService(store=entries, projector=projector,
            memory=memory, interval_seconds=0)
        result = await recovery.start()
        await recovery.stop()
        assert result.recovered == 1 and result.failed == 0
        current = await entries.get(entry.entry_id)
        assert current.l1_event_id == expected_id
        event = await memory.l1.get_event(expected_id)
        assert event['user_id'] == 'local_user'
        if original_id:
            assert (await memory.l1.get_event(original_id))['deleted_at'] is not None
        await memory.flush_l2_projection_jobs()
        for _ in range(800):
            assertions = await memory.l2.list_current_assertions(entity_id='user:local_user')
            if assertions:
                break
            await asyncio.sleep(.01)
        assert [(item['trait_name'], item['trait_value']) for item in assertions] == [('identity.real_name', '明日香')]
        repeated = await recovery.start()
        await recovery.stop()
        assert repeated.recovered == 0 and repeated.failed == 0
        assert (await entries.get(entry.entry_id)).l1_event_id == expected_id
    finally:
        await memory.shutdown()
