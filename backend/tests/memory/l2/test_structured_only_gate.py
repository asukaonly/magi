"""Gate that lets a source-declared structured-only event skip LLM phase1/2.

When a sensor sets ``allow_llm_extraction=False`` (carried in ``metadata_json``),
L2 still does deterministic direct-writes but must NOT call the LLM extractor.
"""

from magi.memory.l2.pipeline.extraction import event_allows_llm_extraction


class _Event:
    def __init__(self, metadata_json):
        self.metadata_json = metadata_json


def test_allows_when_flag_absent():
    assert event_allows_llm_extraction(_Event({})) is True
    assert event_allows_llm_extraction(_Event(None)) is True
    assert event_allows_llm_extraction(_Event({"activity_snapshot": {}})) is True


def test_blocks_when_flag_false():
    assert event_allows_llm_extraction(_Event({"allow_llm_extraction": False})) is False


def test_allows_when_flag_true():
    assert event_allows_llm_extraction(_Event({"allow_llm_extraction": True})) is True


async def test_batch_admission_counts_each_event_and_excludes_other_keys(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from magi.memory.l2.models import L2BatchEvent
    from magi.memory.l2.pipeline.extraction import L2PipelineExtractionMixin
    from magi.memory.l2.pipeline.extraction_contracts import L2ExtractionEventDecision, L2ExtractionPlan
    from magi.memory.l2.promotion_counter import L2PromotionCounter

    host = L2PipelineExtractionMixin()
    host._promotion_counter = L2PromotionCounter(str(tmp_path / "counter.db"))
    host._load_batch_contexts = AsyncMock(return_value=([], []))
    host._resolve_batch_extraction_profile = Mock(return_value=SimpleNamespace(profile_id="source.browser"))
    host._resolve_self_entity_id = Mock(return_value="user:self")
    host._fetch_pinned_payloads = AsyncMock(return_value={})
    host._serialize_event_for_batch = lambda event: L2BatchEvent(event_id=event.event_id, content=event.content)
    host._load_batch_existing_entities = AsyncMock(return_value=[])
    host._build_catalog_name_index = AsyncMock(return_value={})
    host._prepare_direct_graph_writes = AsyncMock(return_value=([], 0))
    decisions = []
    for event_id, key, override in [
        ("a1", "a", ""), ("b1", "b", ""), ("a2", "a", ""),
        ("a3", "a", ""), ("forced", "a", "force_structured_only"),
    ]:
        event = SimpleNamespace(
            event_id=event_id, source="browser", content=event_id, session_id=None, user_id="u1",
            metadata_json={"promotion_key": key, "promotion_threshold": 3, "promotion_override": override},
        )
        decisions.append(L2ExtractionEventDecision(event, SimpleNamespace(evidence_class="external_observation"), SimpleNamespace(allow_graph_write=True)))
    plan = L2ExtractionPlan(decisions, decisions, decisions[-1], [item.event.event_id for item in decisions], None)
    job = SimpleNamespace(attempt_key="attempt:one", bucket_key="batch:one", projection_leases=[])
    batch = await host._prepare_extraction_batch(plan, decisions[-1], job=job)
    assert batch.event_window.event_ids == ["a3"]
    assert batch.event_window.texts == ["a3"]
    assert batch.stored_event.event_id == "a3"
    assert batch.batch_event_ids == ["a1", "b1", "a2", "a3", "forced"]
    assert await host._promotion_counter.bump("browser", "a", "a3", threshold=3) == (3, True)
    assert await host._promotion_counter.bump("browser", "b", "b1", threshold=3) == (1, False)
