"""Authoritative query modes change actual fusion weights and returned event order."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from magi.memory.hybrid_retrieval.l1_handler import L1Handler
from magi.memory.hybrid_retrieval.models import ConversationTurn, RetrievalConfig, RetrievalQuery
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,indexical,weights,expected",
    [
        (None, False, (3.0, 0.1, 0.0), ["lexical", "semantic"]),
        ("summary", False, (0.8, 1.0, 0.4), ["semantic", "lexical"]),
        (None, True, (1.0, 1.2, 0.6), ["semantic", "lexical"]),
    ],
)
async def test_only_authoritative_modes_change_executed_weights_and_ranking(
    monkeypatch, tmp_path, mode, indexical, weights, expected
):
    # Search sources are deterministic; weighting, fusion, hydration and service routing are real.
    monkeypatch.setattr(L1Handler, "_bm25_path", AsyncMock(return_value=["lexical", "semantic"]))
    monkeypatch.setattr(L1Handler, "_vector_path", AsyncMock(return_value=["semantic", "lexical"]))
    for name in ["_keyword_path", "_temporal_bm25_path", "_entity_expansion_path"]:
        monkeypatch.setattr(L1Handler, name, AsyncMock(return_value=[]))
    observed = []

    async def fetch(self, *, event_ids, **kwargs):
        observed.append(
            (
                self._config.rrf_weight_bm25,
                self._config.rrf_weight_vector,
                self._config.rrf_weight_keyword,
            )
        )
        return [
            {
                "event_id": identity,
                "content": "same evidence",
                "timestamp": 1700000100.0,
                "event_type": "user_message",
                "source": "chat",
                "user_id": "u1",
            }
            for identity in event_ids
        ]

    monkeypatch.setattr(L1Handler, "_fetch_and_filter", fetch)
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l2.store import L2CognitionStore

    path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(path)
    l2 = L2CognitionStore(db_path=path)
    await l2.initialize()
    store = SimpleNamespace(fetch_events=AsyncMock(return_value=[]))
    memory = SimpleNamespace(l0=None, l1=store, l2=l2, l2_entity_catalog=None, l3=None, l4=None)
    config = RetrievalConfig(
        intent_decider_llm_enabled=False,
        rrf_weight_bm25=3.0,
        rrf_weight_vector=0.1,
        rrf_weight_keyword=0.0,
        reranker_layers=(),
    )
    service = HybridRetrievalService(memory, config=config)
    tracker = MagicMock(wraps=service._l1.with_config)
    monkeypatch.setattr(service._l1, "with_config", tracker)
    turns = (
        [
            ConversationTurn(role="user", content="q", timestamp=1700000070.0),
            ConversationTurn(role="assistant", content="a", timestamp=1700000100.0),
        ]
        if indexical
        else None
    )
    result = await service.query(
        RetrievalQuery(
            query="当时我说什么" if indexical else "总结一下我最近的活动",
            query_mode=mode,
            conversation_context=turns,
        )
    )
    assert observed and all(actual == weights for actual in observed)
    assert [event["event_id"] for event in result.l1_events] == expected
    assert result.l1_events[0]["retrieval_score"] > result.l1_events[1]["retrieval_score"]
    if mode or indexical:
        tracker.assert_called_once()
        applied = tracker.call_args.args[0]
        assert (
            applied.rrf_weight_bm25,
            applied.rrf_weight_vector,
            applied.rrf_weight_keyword,
        ) == weights
        assert result.trace["mode_rrf_applied"] is True
    else:
        tracker.assert_not_called()
        assert result.trace.get("mode_rrf_applied") is not True
    assert result.trace["mode_source"] == (
        "indexical_override" if indexical else "caller" if mode else "default"
    )
