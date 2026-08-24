from __future__ import annotations

import hashlib
import sqlite3

import pytest

from magi.agent.execution.contracts import AgentRunEventType, RunContextManifest
from magi.agent.execution.context_fingerprint import (
    context_source_refs,
    effective_context_fingerprint,
    message_fingerprints,
)
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
        system_prompt_size_bytes=6,
        message_fingerprints=message_fingerprints(({"role": "user", "content": "hello"},)),
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
        system_prompt_size_bytes=0,
        message_fingerprints=(),
        tool_catalog=(),
        tool_schema_hashes={},
    )

    await journal.record_manifest(manifest)

    with pytest.raises(ValueError, match="only be recorded once"):
        await journal.record_manifest(manifest)


@pytest.mark.asyncio
async def test_run_journal_resume_continues_persisted_sequence(tmp_path) -> None:
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    first = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        store=store,
    )
    await first.record_manifest(
        RunContextManifest(
            run_id="run-1",
            turn_id="turn-1",
            session_id="session-1",
            user_id="user-1",
            prompt_assembly_version="test-v1",
            system_prompt_hash="hash",
            system_prompt_size_bytes=0,
            message_fingerprints=(),
            tool_catalog=(),
            tool_schema_hashes={},
        )
    )
    await first.append(AgentRunEventType.RUN_STARTED)

    resumed = AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        store=store,
    )
    await resumed.resume()
    event = await resumed.append(AgentRunEventType.STEP_STARTED, step_index=1)

    assert event.sequence == 2
    assert [item["sequence"] for item in await store.list_run_events("run-1")] == [1, 2]
    await store.shutdown()


@pytest.mark.asyncio
async def test_run_manifest_insert_does_not_overwrite_existing_run(tmp_path) -> None:
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()
    manifest = RunContextManifest(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        prompt_assembly_version="test-v1",
        system_prompt_hash="hash",
        system_prompt_size_bytes=1,
        message_fingerprints=(),
        tool_catalog=(),
        tool_schema_hashes={},
    )

    await AgentRunJournal(
        run_id="run-1",
        turn_id="turn-1",
        session_id="session-1",
        user_id="user-1",
        store=store,
    ).record_manifest(manifest)

    with pytest.raises(sqlite3.IntegrityError):
        await AgentRunJournal(
            run_id="run-1",
            turn_id="turn-2",
            session_id="session-1",
            user_id="user-1",
            store=store,
        ).record_manifest(manifest)
    assert (await store.get_run_manifest("run-1"))["turn_id"] == "turn-1"
    await store.shutdown()


def test_durable_context_records_do_not_copy_prompt_or_attachment_content() -> None:
    secret = "private-history-value"
    image = "data:image/png;base64," + "A" * 100_000
    messages = (
        {
            "role": "user",
            "content": [
                {"type": "text", "text": secret},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        },
    )
    fingerprints = message_fingerprints(messages)
    source_refs = context_source_refs(
        ({"source": "memory", "memory_id": "memory-1", "rendered": secret},)
    )
    event = effective_context_fingerprint(
        mode="tool_loop",
        system_prompt=f"system {secret}",
        messages=list(messages),
        tools=[{"function": {"name": "read_file", "description": secret}}],
        reasoning_state={"effective_depth": "low"},
    )

    durable_text = str((fingerprints, source_refs, event))
    assert secret not in durable_text
    assert image not in durable_text
    assert fingerprints[0]["has_images"] is True
    assert fingerprints[0]["size_bytes"] > 100_000
