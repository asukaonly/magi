"""Default retrieval policies exercised at their consuming boundaries."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from magi.memory.hybrid_retrieval import build_query
from magi.memory.hybrid_retrieval.handlers import L3Handler, L4Handler
from magi.memory.hybrid_retrieval.models import L3Conditions, L4Conditions
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "layer,handler_type,conditions_type,id_key",
    [("L3", L3Handler, L3Conditions, "summary_id"), ("L4", L4Handler, L4Conditions, "skill_id")],
)
async def test_default_summary_and_procedure_queries_bound_results_without_category_filters(
    layer, handler_type, conditions_type, id_key
):
    from magi.memory.hybrid_retrieval import handler_base

    rows = [
        {
            id_key: f"item-{index}",
            "content": "shared evidence",
            "optimized_prompt": "shared evidence",
            "summary_type": "temporal" if index % 2 else "insight",
            "summary_category": "music" if index % 2 else "work",
            "skill_category": "tool" if index % 2 else "workflow",
        }
        for index in range(8)
    ]
    store = SimpleNamespace(
        bm25_search=AsyncMock(return_value=[(row[id_key], -1.0) for row in rows]),
        vector_search=AsyncMock(return_value=[]),
        keyword_search=AsyncMock(return_value=[]),
        fetch_by_ids=AsyncMock(return_value=rows),
    )
    with patch.object(handler_base, "rrf_fuse", wraps=handler_base.rrf_fuse) as fuse:
        result = await handler_type(store).execute(conditions_type(content_query="shared evidence"))
    assert len(result) == 5
    assert [row[id_key] for row in result] == [f"item-{index}" for index in range(5)]
    fuse.assert_called_once()
    assert fuse.call_args.kwargs["k"] == 60
    if layer == "L3":
        assert {row["summary_type"] for row in result} == {"temporal", "insight"}
        assert {row["summary_category"] for row in result} == {"music", "work"}
        assert store.fetch_by_ids.await_args.kwargs == {
            "summary_type": None,
            "summary_category": None,
        }
    else:
        assert {row["skill_category"] for row in result} == {"tool", "workflow"}
        assert store.fetch_by_ids.await_args.kwargs == {}


@pytest.mark.asyncio
async def test_default_service_uses_model_intent_and_passes_budget_to_real_fusion():
    bridge = SimpleNamespace(
        chat=AsyncMock(
            return_value=json.dumps(
                {"query_mode": "event_stream", "content_query": "my recent notes"}
            )
        )
    )
    memory = SimpleNamespace(l0=None, l1=None, l2=None, l3=None, l4=None, memory_db_path=None)
    service = HybridRetrievalService(memory, llm_provider_bridge=bridge)
    with patch.object(service._result_fusion, "apply", wraps=service._result_fusion.apply) as fuse:
        result = await service.query(build_query(query="my recent notes"))
    calls = [
        call.kwargs
        for call in bridge.chat.await_args_list
        if call.kwargs.get("event_context", {}).get("request_kind")
        == "memory:hybrid_retrieval_intent"
    ]
    assert len(calls) == 1
    assert "my recent notes" in calls[0]["messages"][0]["content"]
    assert calls[0]["json_mode"] is True
    fuse.assert_called_once()
    assert fuse.call_args.kwargs == {"max_tokens": 16384}
    assert result.l1_events == []
