from __future__ import annotations

import hashlib

import pytest

from magi.agent.execution.contracts import AgentRunEventType, RunContextManifest
from magi.agent.execution.journal import AgentRunJournal
from magi.runtime_trace import RuntimeTraceStore


@pytest.mark.asyncio
async def test_run_journal_persists_manifest_and_ordered_events(tmp_path) -> None:
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    journal = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        store=store,
    )
    manifest = RunContextManifest(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        prompt_assembly_version="test-v1",
        system_prompt_hash=hashlib.sha256(b"system").hexdigest(),
        messages=({"role": "user", "content": "hello"},),
        tool_catalog=("memory_query",),
        tool_schema_hashes={"memory_query": "schema-hash"},
        created_at_ms=100,
    )

    await journal.record_manifest(manifest)
    await journal.append(AgentRunEventType.RUN_STARTED)
    await journal.append(
        AgentRunEventType.STEP_STARTED,
        step_index=1,
        payload={"depth": "low"},
    )

    persisted_manifest = await store.get_run_manifest("run-1")
    events = await store.list_run_events("run-1")

    assert persisted_manifest == manifest.to_dict()
    assert [item["sequence"] for item in events] == [1, 2]
    assert [item["event_type"] for item in events] == [
        "run_started",
        "step_started",
    ]
    assert events[1]["payload"] == {"depth": "low"}
    await store.shutdown()


@pytest.mark.asyncio
async def test_run_manifest_is_recorded_once() -> None:
    journal = AgentRunJournal(
        run_id="run-1",
        turn_id=None,
        session_id=None,
        user_id=None,
    )
    manifest = RunContextManifest(
        run_id="run-1",
        turn_id=None,
        session_id=None,
        user_id=None,
        prompt_assembly_version="test-v1",
        system_prompt_hash="hash",
        messages=(),
        tool_catalog=(),
        tool_schema_hashes={},
    )

    await journal.record_manifest(manifest)

    with pytest.raises(ValueError, match="only be recorded once"):
        await journal.record_manifest(manifest)
