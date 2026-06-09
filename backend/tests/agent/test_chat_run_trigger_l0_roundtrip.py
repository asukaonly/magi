"""ADR-0004 P3 (3b): RunTrigger persists with the run across L0 checkpoint/restore.

This is the *real* L0 round-trip (real L0WorkingMemoryStore + real SQLite file +
two store instances simulating a restart), not a SimpleNamespace / hand-built
AgentRun. It proves the trigger now survives restart / background restore and
that the coordinator's origin-channel delivery fan-out (which reads
``active_run.trigger.source_channel``) stays intact.
"""
from __future__ import annotations

import pytest

from magi_plugin_sdk.run_trigger import RunTrigger

from magi.chat.task_agent.run_store import SessionRunStore
from magi.memory.l0.working_memory import L0WorkingMemoryStore


@pytest.mark.asyncio
async def test_trigger_survives_l0_checkpoint_restore(tmp_path) -> None:
    db = str(tmp_path / "l0.db")

    l0a = L0WorkingMemoryStore(checkpoint_db_path=db, restore_on_restart=False)
    await l0a.initialize()
    await l0a.start_session(session_id="s-wx", user_id="u-wx", runtime_agent_id="chat:u-wx")
    store_a = SessionRunStore(l0_store=l0a)

    trigger = RunTrigger(
        trigger_type="external_inbound",
        source_channel="weixin",
        requester="u-wx",
        priority="foreground",
        payload={"content": "你好"},
    )
    store_a.create_active_run(session_id="s-wx", run_id="run-wx", trigger=trigger)
    await l0a.checkpoint_session("s-wx")

    # Fresh store, same DB → simulates a restart / background restore.
    l0b = L0WorkingMemoryStore(checkpoint_db_path=db, restore_on_restart=True)
    await l0b.initialize()
    store_b = SessionRunStore(l0_store=l0b)

    restored = store_b.get_active_run("s-wx")
    assert restored is not None
    assert restored.trigger is not None                  # was None before 3b-2
    assert restored.trigger.trigger_type == "external_inbound"
    assert restored.trigger.source_channel == "weixin"   # origin-channel link intact
    assert restored.trigger.payload["content"] == "你好"  # lossless JSON round-trip


@pytest.mark.asyncio
async def test_run_without_trigger_restores_as_none(tmp_path) -> None:
    db = str(tmp_path / "l0.db")
    l0a = L0WorkingMemoryStore(checkpoint_db_path=db, restore_on_restart=False)
    await l0a.initialize()
    await l0a.start_session(session_id="s2", user_id="u2", runtime_agent_id="chat:u2")
    store_a = SessionRunStore(l0_store=l0a)
    store_a.create_active_run(session_id="s2", run_id="run2")  # no trigger
    await l0a.checkpoint_session("s2")

    l0b = L0WorkingMemoryStore(checkpoint_db_path=db, restore_on_restart=True)
    await l0b.initialize()
    store_b = SessionRunStore(l0_store=l0b)
    restored = store_b.get_active_run("s2")
    assert restored is not None
    assert restored.trigger is None
