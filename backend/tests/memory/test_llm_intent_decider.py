"""Tests for LLMIntentDecider."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.intent_decider import LLMIntentDecider
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
)


@pytest.fixture
def mock_bridge():
    return AsyncMock()


@pytest.fixture
def decider(mock_bridge):
    return LLMIntentDecider(mock_bridge, timeout_seconds=3.0)


# -----------------------------------------------------------------------
# Successful parsing
# -----------------------------------------------------------------------


class TestLLMParsing:
    @pytest.mark.asyncio
    async def test_single_l1_layer(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L1",
                    "is_fallback": False,
                    "content_query": "browsing history",
                    "source_filters": ["chrome_history"],
                }
            ],
            "reasoning": "user asked about browsing",
        })
        inp = IntentDeciderInput(query="what did I browse")
        result = await decider.evaluate(inp)

        assert result is not None
        assert result.source == "llm"
        assert len(result.plans) == 1
        assert result.plans[0].layer == "L1"
        assert isinstance(result.plans[0].conditions, L1Conditions)
        assert result.plans[0].conditions.content_query == "browsing history"
        assert result.reasoning == "user asked about browsing"

    @pytest.mark.asyncio
    async def test_multi_layer(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L4", "is_fallback": False, "content_query": "deploy"},
                {"layer": "L1", "is_fallback": True, "content_query": "deploy"},
            ],
            "reasoning": "experience query",
        })
        inp = IntentDeciderInput(query="how to deploy")
        result = await decider.evaluate(inp)

        assert result is not None
        assert len(result.plans) == 2
        assert result.plans[0].layer == "L4"
        assert not result.plans[0].is_fallback
        assert result.plans[1].layer == "L1"
        assert result.plans[1].is_fallback

    @pytest.mark.asyncio
    async def test_l2_with_entities(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L2",
                    "is_fallback": False,
                    "content_query": "Alice 和 Bob 的关系",
                    "entities": ["Alice", "Bob"],
                    "subject_hint": "explicit",
                    "predicate_family": "relationship",
                }
            ],
            "reasoning": "relationship query",
        })
        inp = IntentDeciderInput(query="Alice和Bob什么关系")
        result = await decider.evaluate(inp)

        assert result is not None
        assert result.plans[0].layer == "L2"
        assert isinstance(result.plans[0].conditions, L2Conditions)
        assert result.plans[0].conditions.entities == ["Alice", "Bob"]
        assert result.plans[0].conditions.subject_hint == "explicit"
        assert result.plans[0].conditions.predicate_family == "relationship"

    @pytest.mark.asyncio
    async def test_l2_with_semantic_frame(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L2",
                    "is_fallback": False,
                    "content_query": "B站 喜欢的 up 主",
                    "entities": ["B站"],
                    "subject_hint": "self",
                    "predicate_family": "preference",
                    "semantic_frame": {
                        "query_family": "affinity",
                        "subject_scope": "self",
                        "answer_kind": "creator",
                        "answer_unit": "identity",
                        "answer_shape": "list",
                        "polarity": "positive",
                        "constraints": [
                            {
                                "scope": "target",
                                "facet": "platform",
                                "raw_value": "B站",
                                "resolved_entity_id": "software:bilibili",
                            }
                        ],
                    },
                }
            ],
            "reasoning": "creator affinity query",
        })

        result = await decider.evaluate(IntentDeciderInput(query="我B站喜欢哪些up主"))

        assert result is not None
        assert isinstance(result.plans[0].conditions, L2Conditions)
        assert isinstance(result.plans[0].conditions.semantic_frame, L2SemanticFrame)
        assert result.plans[0].conditions.semantic_frame.answer_kind == "creator"
        assert result.plans[0].conditions.semantic_frame.constraints[0].resolved_entity_id == "software:bilibili"

    @pytest.mark.asyncio
    async def test_l2_with_place_semantic_frame(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L2",
                    "is_fallback": False,
                    "content_query": "杭州 喜欢去的 咖啡馆",
                    "subject_hint": "self",
                    "predicate_family": "preference",
                    "semantic_frame": {
                        "query_family": "affinity",
                        "subject_scope": "self",
                        "answer_kind": "place",
                        "answer_unit": "place",
                        "answer_shape": "list",
                        "polarity": "positive",
                        "constraints": [
                            {
                                "scope": "target",
                                "facet": "located_in",
                                "raw_value": "杭州",
                                "resolved_entity_id": "place:hangzhou",
                            },
                            {
                                "scope": "target",
                                "facet": "category",
                                "raw_value": "咖啡馆",
                                "resolved_facet_value": "coffee_shop",
                            },
                        ],
                    },
                }
            ],
            "reasoning": "place affinity query",
        })

        result = await decider.evaluate(IntentDeciderInput(query="我在杭州喜欢去哪些咖啡馆"))

        assert result is not None
        frame = result.plans[0].conditions.semantic_frame
        assert isinstance(frame, L2SemanticFrame)
        assert frame.answer_kind == "place"
        assert frame.constraints[0].resolved_entity_id == "place:hangzhou"
        assert frame.constraints[1].resolved_facet_value == "coffee_shop"

    @pytest.mark.asyncio
    async def test_l2_with_interaction_scoped_place_semantic_frame(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L2",
                    "is_fallback": False,
                    "content_query": "在杭州的时候 喜欢去的 咖啡馆",
                    "subject_hint": "self",
                    "predicate_family": "preference",
                    "semantic_frame": {
                        "query_family": "affinity",
                        "subject_scope": "self",
                        "answer_kind": "place",
                        "answer_unit": "place",
                        "answer_shape": "list",
                        "polarity": "positive",
                        "constraints": [
                            {
                                "scope": "interaction",
                                "facet": "located_in",
                                "raw_value": "杭州",
                                "resolved_entity_id": "place:hangzhou",
                            },
                            {
                                "scope": "target",
                                "facet": "category",
                                "raw_value": "咖啡馆",
                                "resolved_facet_value": "coffee_shop",
                            },
                        ],
                    },
                }
            ],
            "reasoning": "interaction-scoped place affinity query",
        })

        result = await decider.evaluate(IntentDeciderInput(query="我在杭州的时候喜欢去哪些咖啡馆"))

        assert result is not None
        frame = result.plans[0].conditions.semantic_frame
        assert isinstance(frame, L2SemanticFrame)
        assert frame.answer_kind == "place"
        assert [(item.scope, item.facet, item.raw_value) for item in frame.constraints] == [
            ("interaction", "located_in", "杭州"),
            ("target", "category", "咖啡馆"),
        ]

    @pytest.mark.asyncio
    async def test_l3_layer(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L3", "is_fallback": False, "content_query": "weekly review"},
            ],
            "reasoning": "summary",
        })
        inp = IntentDeciderInput(query="summarize this week")
        result = await decider.evaluate(inp)

        assert result is not None
        assert isinstance(result.plans[0].conditions, L3Conditions)

    @pytest.mark.asyncio
    async def test_rewrites_overly_broad_quoted_l1_query_back_to_original_query(self, decider: LLMIntentDecider, mock_bridge):
        query = "How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?"
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L1",
                    "is_fallback": False,
                    "content_query": "communication skills workshop and meeting preparation",
                }
            ],
            "reasoning": "temporal distance query",
        })

        result = await decider.evaluate(IntentDeciderInput(query=query))

        assert result is not None
        assert isinstance(result.plans[0].conditions, L1Conditions)
        assert result.plans[0].conditions.content_query == query

    @pytest.mark.asyncio
    async def test_rewrites_overly_broad_unquoted_comparison_query_back_to_original_query(self, decider: LLMIntentDecider, mock_bridge):
        query = "Which vehicle did I take care of first in February, the bike or the car?"
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {
                    "layer": "L1",
                    "is_fallback": False,
                    "content_query": "vehicle maintenance in february",
                }
            ],
            "reasoning": "comparison query",
        })

        result = await decider.evaluate(IntentDeciderInput(query=query))

        assert result is not None
        assert isinstance(result.plans[0].conditions, L1Conditions)
        assert result.plans[0].conditions.content_query == query

    @pytest.mark.asyncio
    async def test_preserves_specific_anchor_queries_when_llm_already_returns_them(self, decider: LLMIntentDecider, mock_bridge):
        query = "Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?"
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L1", "is_fallback": False, "content_query": "Effective Time Management workshop"},
                {"layer": "L1", "is_fallback": False, "content_query": "Data Analysis using Python webinar"},
            ],
            "reasoning": "comparison query",
        })

        result = await decider.evaluate(IntentDeciderInput(query=query))

        assert result is not None
        assert [plan.conditions.content_query for plan in result.plans] == [
            "Effective Time Management workshop",
            "Data Analysis using Python webinar",
        ]


# -----------------------------------------------------------------------
# Failure modes → returns None
# -----------------------------------------------------------------------


class TestLLMFailures:
    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.side_effect = TimeoutError("timeout")
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = "not valid json at all"
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_layers_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"layers": [], "reasoning": "empty"})
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_layers_key_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"reasoning": "no layers"})
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_layer_name_skipped(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L99", "is_fallback": False, "content_query": "x"},
            ],
            "reasoning": "bad layer",
        })
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is None  # all layers invalid → no plans → None

    @pytest.mark.asyncio
    async def test_mixed_valid_invalid_layers(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [
                {"layer": "L99", "is_fallback": False, "content_query": "x"},
                {"layer": "L1", "is_fallback": False, "content_query": "valid"},
            ],
            "reasoning": "mixed",
        })
        inp = IntentDeciderInput(query="hello")
        result = await decider.evaluate(inp)
        assert result is not None
        assert len(result.plans) == 1
        assert result.plans[0].layer == "L1"


# -----------------------------------------------------------------------
# LLM call parameters
# -----------------------------------------------------------------------


class TestLLMCallParams:
    @pytest.mark.asyncio
    async def test_chat_called_with_correct_params(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "x"}],
            "reasoning": "ok",
        })
        inp = IntentDeciderInput(query="test query")
        await decider.evaluate(inp)

        mock_bridge.chat.assert_called_once()
        call_kwargs = mock_bridge.chat.call_args
        assert call_kwargs.kwargs["max_tokens"] == 512
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["disable_thinking"] is True
        assert call_kwargs.kwargs["json_mode"] is True
        assert call_kwargs.kwargs["timeout_seconds"] == 3.0
        assert "test query" in call_kwargs.kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_chat_prompt_includes_recall_intent_hint(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L2", "is_fallback": False, "content_query": "weather preference"}],
            "reasoning": "ok",
        })

        inp = IntentDeciderInput(query="我喜欢什么天气", recall_intent_hint="preference_recall")
        await decider.evaluate(inp)

        prompt = mock_bridge.chat.call_args.kwargs["messages"][0]["content"]
        assert "preference_recall" in prompt

    @pytest.mark.asyncio
    async def test_system_prompt_preserves_quoted_titles(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "x"}],
            "reasoning": "ok",
        })

        await decider.evaluate(
            IntentDeciderInput(
                query="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?"
            )
        )

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        assert "Keep quoted titles verbatim" in system_prompt
        assert "Do not replace a quoted title with a broad topic" in system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_guides_comparison_and_temporal_distance_queries(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L1", "is_fallback": False, "content_query": "x"}],
            "reasoning": "ok",
        })

        await decider.evaluate(
            IntentDeciderInput(
                query="How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?"
            )
        )

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        assert "For comparison questions, keep both candidate events explicit" in system_prompt
        assert "For temporal-distance questions, produce anchor-specific content_query text" in system_prompt
        assert "Do not collapse both anchors into one generic topic query" in system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_includes_l2_subject_and_predicate_contract(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "layers": [{"layer": "L2", "is_fallback": False, "content_query": "天气偏好"}],
            "reasoning": "ok",
        })

        await decider.evaluate(IntentDeciderInput(query="我喜欢什么天气"))

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        assert 'set subject_hint to "self"' in system_prompt
        assert "Allowed predicate_family values" in system_prompt
        assert '"semantic_frame"' in system_prompt
        assert '"answer_kind"' in system_prompt
