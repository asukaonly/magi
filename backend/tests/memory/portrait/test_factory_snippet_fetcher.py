from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.chat.portrait.contracts import TopicResult
from magi.memory.portrait.snippet_fetcher import build_snippet_fetcher


def _payload(*, l3=None, l2_assertions=None, l2_relationships=None, l4=None):
    return SimpleNamespace(
        l0_workbench=[],
        l1_events=[],
        l1_evidence_bundles=[],
        l1_timeline_summary=[],
        l2_entity_cards=[],
        l2_relationships=l2_relationships or [],
        l2_assertions=l2_assertions or [],
        l3_reflections=l3 or [],
        l4_procedures=l4 or [],
        l2_episodes=[],
        l2_state_facts=[],
        l2_state_history=[],
        trace={},
    )


@pytest.mark.asyncio
async def test_empty_topic_skips_retrieval():
    service = AsyncMock()
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    result = await fetcher("u1", TopicResult(topic="", entities=[]))
    assert result == []
    service.query.assert_not_called()


@pytest.mark.asyncio
async def test_aggregates_l2_l3_l4_into_snippets():
    service = AsyncMock()
    service.query = AsyncMock(return_value=_payload(
        l3=[{"summary_id": "s1", "content": "对失败者同理", "confidence": 0.8}],
        l2_assertions=[{"assertion_id": "a1", "statement": "不喜欢直播", "confidence": 0.9}],
        l2_relationships=[{"relationship_id": "r1", "subject": "self",
                           "predicate": "LIKES", "object": "Primal Scream",
                           "confidence": 0.7}],
        l4=[{"procedure_id": "p1", "title": "部署 Magi"}],
    ))
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    snippets = await fetcher("u1", TopicResult(topic="罗永浩", entities=["锤子"]))
    kinds = [s.kind for s in snippets]
    assert "reflection" in kinds
    assert "assertion" in kinds
    assert "relationship" in kinds
    assert "procedure" in kinds
    assert all(s.layer in {"L2", "L3", "L4"} for s in snippets)


@pytest.mark.asyncio
async def test_limit_caps_snippets_to_15():
    service = AsyncMock()
    service.query = AsyncMock(return_value=_payload(
        l3=[{"summary_id": f"s{i}", "content": f"r{i}", "confidence": 0.5} for i in range(30)],
    ))
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: service)
    snippets = await fetcher("u1", TopicResult(topic="t", entities=[]))
    assert len(snippets) <= 15


@pytest.mark.asyncio
async def test_no_service_returns_empty():
    fetcher = build_snippet_fetcher(retrieval_service_provider=lambda: None)
    result = await fetcher("u1", TopicResult(topic="t", entities=[]))
    assert result == []
