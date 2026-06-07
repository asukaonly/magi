import pytest

from magi.memory.l1.writes import _merge_evidence_into_metadata


def test_merge_into_empty_metadata_creates_evidence_namespace():
    assert _merge_evidence_into_metadata(None, "user_question_lead_or_mark") == {
        "_evidence": {"reason_code": "user_question_lead_or_mark"}
    }


def test_merge_preserves_existing_metadata():
    out = _merge_evidence_into_metadata({"foo": 1}, "user_default")
    assert out == {"foo": 1, "_evidence": {"reason_code": "user_default"}}


def test_merge_with_no_reason_code_and_no_metadata_returns_none():
    assert _merge_evidence_into_metadata(None, None) is None


def test_merge_with_no_reason_code_keeps_metadata():
    assert _merge_evidence_into_metadata({"foo": 1}, None) == {"foo": 1}


def test_merge_does_not_clobber_existing_evidence_keys():
    out = _merge_evidence_into_metadata({"_evidence": {"other": 2}}, "user_default")
    assert out == {"_evidence": {"other": 2, "reason_code": "user_default"}}


def _migrated_l1_db_path(tmp_path):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths

    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")
    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


@pytest.mark.asyncio
async def test_store_persists_reason_code_into_metadata_json_evidence(tmp_path):
    from magi.events.events import Event, EventLevel, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        event = normalize_runtime_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={
                    "user_id": "user-1",
                    "session_id": "session-1",
                    "content": "杭州天气怎么样",
                    "author_type": "user",
                    "content_type": "text",
                },
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-reason-code-1",
                event_id="evt-reason-code-1",
            )
        )

        await store.store(event)
        read = await store.get_event(event.event_id)

        assert read is not None
        assert read["evidence_class"] == "user_question"
        assert read["metadata_json"]["_evidence"]["reason_code"] == "user_question_lead_or_mark"
    finally:
        await store.shutdown()
