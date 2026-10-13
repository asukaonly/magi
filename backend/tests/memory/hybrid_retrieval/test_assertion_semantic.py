"""Semantic relevance selects source facts without widening memory governance."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from magi.memory.hybrid_retrieval.assertion_semantic import (
    AssertionSemanticSelector,
    BATCH_SIZE,
    MAX_CANDIDATES,
    MAX_FACT_CHARS,
)
from magi.memory.hybrid_retrieval.l2_handler import L2Handler
from magi.memory.hybrid_retrieval.models import (
    AssertionQuery,
    L2Conditions,
    L2SemanticFrame,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.retrieval_projection import project_historical_recall
from memory.l2.test_preference_exclusions import _open
from memory.l2.test_preference_lifecycle import _claim_response, _ingest_response
from memory.hybrid_retrieval.test_assertion_relevance import _seed


def _row(identity, target):
    return {
        "assertion_id": identity,
        "trait_name": "preference.affinity",
        "trait_value": "like",
        "target": target,
    }


def _selector(bridge, timeout=1):
    return AssertionSemanticSelector(
        bridge,
        selection=AssertionQuery(predicates=["LIKES"], value_scope="constrained"),
        timeout=timeout,
    )


class _Bridge:
    def __init__(self, response=None):
        self.response = response
        self.calls = []

    async def chat(self, **kwargs):
        # OpenAI-compatible JSON response mode requires this explicit cue.
        assert "json" in kwargs["system_prompt"].lower()
        request = json.loads(kwargs["messages"][0]["content"])
        self.calls.append(request)
        if self.response is not None:
            return self.response
        return json.dumps(
            {
                "keep": [
                    item["index"] for item in request["candidates"] if item["target"] == "爵士乐"
                ]
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["我喜欢什么音乐？", "What music do I like?"])
async def test_selector_matches_concept_without_returning_unrelated_preferences(query):
    bridge = _Bridge()
    selector = _selector(bridge)
    selector.consider([_row("jazz", "爵士乐"), _row("food", "火锅")], [])
    trace = {}
    result = await selector.select(query=query, limit=10, trace=trace)
    assert [item["assertion_id"] for item in result] == ["jazz"]
    assert trace["complete"] is True
    assert bridge.calls[0]["query"] == query
    assert all(
        set(item) == {"index", "trait", "value", "target"} for item in bridge.calls[0]["candidates"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ["garbage", "[]", '{"keep":[true]}', '{"keep":[99]}', '{"keep":[0],"answer":"invented"}']
)
async def test_invalid_model_output_never_passes_candidates_through(raw):
    selector = _selector(_Bridge(raw))
    selector.consider([_row("jazz", "爵士乐")], [])
    trace = {}
    assert await selector.select(query="music", limit=10, trace=trace) is None
    assert trace["complete"] is False
    assert trace["reason"] == "model_or_response_error"


@pytest.mark.asyncio
async def test_provider_failure_keeps_selection_incomplete():
    class FailingBridge:
        async def chat(self, **kwargs):
            raise RuntimeError("Provider unavailable")

    selector = _selector(FailingBridge())
    selector.consider([_row("jazz", "爵士乐")], [])
    trace = {}
    assert await selector.select(query="music", limit=10, trace=trace) is None
    assert trace["complete"] is False
    assert trace["reason"] == "model_or_response_error"
    assert trace["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_provider_http_failure_reports_only_safe_metadata(caplog):
    class ProviderFailure(RuntimeError):
        status_code = 400

    class FailingBridge:
        async def chat(self, **kwargs):
            raise ProviderFailure("SECRET_CANDIDATE_BODY")

    selector = _selector(FailingBridge())
    selector.consider([_row("jazz", "爵士乐")], [])
    trace = {}
    assert await selector.select(query="music", limit=10, trace=trace) is None
    assert trace["error_status"] == 400
    assert trace["error_type"] == "ProviderFailure"
    assert "SECRET_CANDIDATE_BODY" not in json.dumps(trace) + caplog.text


@pytest.mark.asyncio
async def test_valid_empty_selection_is_complete_without_passing_unrelated_facts():
    selector = _selector(_Bridge('{"keep":[]}'))
    selector.consider([_row("food", "火锅")], [])
    trace = {}
    assert await selector.select(query="music", limit=10, trace=trace) == []
    assert trace["complete"] is True


@pytest.mark.asyncio
async def test_model_timeout_cancels_work_with_one_total_budget():
    cancelled = asyncio.Event()

    class SlowBridge:
        async def chat(self, **kwargs):
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.set()

    selector = _selector(SlowBridge(), timeout=0.02)
    selector.consider([_row("jazz", "爵士乐")], [])
    trace = {}
    started = time.monotonic()
    assert await selector.select(query="music", limit=10, trace=trace) is None
    assert time.monotonic() - started < 0.5
    assert cancelled.is_set()
    assert trace["reason"] == "model_timeout"


@pytest.mark.asyncio
async def test_global_shortlist_prefers_old_relevant_fact_and_reports_unjudged_candidates():
    bridge = _Bridge()
    selector = _selector(bridge)
    for page in range(6):
        selector.consider([_row(f"food-{page}-{index}", f"食物{index}") for index in range(50)], [])
    jazz = _row("old-jazz", "爵士乐")
    selector.consider([jazz], [dict(jazz, _query_relevance_score=0.8)])
    selector.consider([_row("oversized", "x" * (MAX_FACT_CHARS + 1))], [])
    trace = {}
    result = await selector.select(query="music", limit=10, trace=trace)
    assert [item["assertion_id"] for item in result] == ["old-jazz"]
    assert sum(len(call["candidates"]) for call in bridge.calls) == MAX_CANDIDATES
    assert all(len(call["candidates"]) <= BATCH_SIZE for call in bridge.calls)
    assert trace["complete"] is False
    assert trace["omitted_count"] == 302 - MAX_CANDIDATES
    assert trace["oversized_count"] == 1


def _conditions():
    return L2Conditions(
        content_query="我喜欢什么音乐",
        original_query="我喜欢什么音乐？不要推荐新音乐。",
        subject_hint="self",
        include_tom_snapshot=False,
        include_relationships=False,
        semantic_frame=L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind="unknown",
            assertion_query=AssertionQuery(predicates=["LIKES"], value_scope="constrained"),
        ),
    )


@pytest.mark.asyncio
async def test_semantic_recall_respects_corrections_and_forgetting_before_sending(tmp_path):
    store, adapter = await _open(tmp_path)
    bridge = _Bridge()
    try:
        for event, target in [("jazz-source", "爵士乐"), ("food-source", "火锅")]:
            text = f"我喜欢{target}"
            await _ingest_response(
                store,
                adapter,
                event,
                text,
                _claim_response(event, text, target=target, text_target=True),
            )
        for name, overrides in [
            ("other", {"user_id": "other"}),
            ("expired", {"expires_at": time.time() - 10}),
            (
                "scoped",
                {
                    "scope": {
                        "all_of": [
                            {"dimension": "project", "context_id": "ctx_project_" + "a" * 64}
                        ]
                    }
                },
            ),
        ]:
            await store.l2_entity_catalog.upsert_entity(
                entity_id=f"other:{name}", canonical_name=f"{name}-CANARY", entity_type="other"
            )
            await _seed(
                store.l2,
                name,
                f"{name}-CANARY",
                **{
                    "user_id": "u1",
                    "trait_name": "preference.affinity",
                    "trait_value": "like",
                    "target_entity_id": f"other:{name}",
                    "target_entity_type": "other",
                    **overrides,
                },
            )
        handler = L2Handler(store.l2, llm_provider_bridge=bridge)
        result = await handler.execute(_conditions(), user_id="u1")
        assert [item["target"] for item in result["assertions"]] == ["爵士乐"]
        assert bridge.calls[-1]["query"] == _conditions().original_query
        assert "CANARY" not in json.dumps(bridge.calls)
        jazz = result["assertions"][0]
        await store.l2.apply_assertion_correction(
            assertion_id=jazz["assertion_id"],
            request_id="change-jazz",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="dislike",
        )
        result = await handler.execute(_conditions(), user_id="u1")
        assert result["assertions"] == []
        assert [item["target"] for item in bridge.calls[-1]["candidates"]] == ["火锅"]
        await store.forget_source_events(["food-source"])
        calls = len(bridge.calls)
        result = await handler.execute(_conditions(), user_id="u1")
        assert result["assertions"] == []
        assert len(bridge.calls) == calls
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_fact_forgotten_while_model_runs_cannot_return(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        text = "我喜欢爵士乐"
        await _ingest_response(
            store,
            adapter,
            "jazz",
            text,
            _claim_response("jazz", text, target="爵士乐", text_target=True),
        )

        class ForgettingBridge:
            async def chat(self, **kwargs):
                await store.forget_source_events(["jazz"])
                return '{"keep":[0]}'

        result = await L2Handler(store.l2, llm_provider_bridge=ForgettingBridge()).execute(
            _conditions(), user_id="u1"
        )
        assert result["assertions"] == []
        assert (
            result["trace"]["assertion_retrieval"]["semantic_selection"]["reason"]
            == "governance_changed"
        )
    finally:
        await store.shutdown()


def test_incomplete_selection_is_not_projected_as_confirmed_absence():
    payload = RetrievalPayload()
    HybridRetrievalService._merge_result(
        payload,
        "L2",
        {
            "trace": {
                "assertion_retrieval": {
                    "semantic_selection": {"complete": False, "reason": "model_timeout"}
                }
            }
        },
    )
    HybridRetrievalService._merge_result(payload, "L2", {"trace": {"assertion_retrieval": {}}})
    result = project_historical_recall(payload=payload, request=RetrievalQuery(query="音乐"))
    assert result.status == "ambiguous"
    assert result.insufficient_evidence is True
    assert result.coverage["kind"] == "partial"
    assert result.answering_hints["must_not_claim_absence"] is True
