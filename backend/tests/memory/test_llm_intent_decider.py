"""Tests for LLMIntentDecider (refinement contract).

The LLM is no longer responsible for layer routing — that is the rule
engine's job (driven by ``query_mode``). ``LLMIntentDecider.evaluate``
returns a flat :class:`LLMRefinement` object that ``IntentDecider``
overlays onto the rule-routed plans via ``LLMIntentDecider.apply``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.intent_decider import (
    LLMIntentDecider,
    LLMRefinement,
)
from magi.memory.hybrid_retrieval.models import (
    IntentDecision,
    IntentDeciderInput,
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
)


@pytest.fixture
def mock_bridge():
    return AsyncMock()


@pytest.fixture
def decider(mock_bridge):
    return LLMIntentDecider(mock_bridge, timeout_seconds=3.0)


def _make_l1_rule_plan(query: str) -> IntentDecision:
    return IntentDecision(
        plans=[LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query=query))],
        reasoning="rule",
        source="rule",
    )


def _make_l2_rule_plan(query: str) -> IntentDecision:
    return IntentDecision(
        plans=[LayerQueryPlan(layer="L2", conditions=L2Conditions(content_query=query))],
        reasoning="rule",
        source="rule",
    )


# -----------------------------------------------------------------------
# Successful parsing → LLMRefinement
# -----------------------------------------------------------------------


class TestLLMParsing:
    @pytest.mark.asyncio
    async def test_minimal_content_query(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "browsing history",
            "reasoning": "user asked about browsing",
        })

        result = await decider.evaluate(IntentDeciderInput(query="what did I browse"))

        assert isinstance(result, LLMRefinement)
        assert result.content_query == "browsing history"
        assert result.reasoning == "user asked about browsing"
        assert result.entities is None
        assert result.semantic_frame is None

    @pytest.mark.asyncio
    async def test_l2_entities_and_predicate_family(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "Alice 和 Bob 的关系",
            "entities": ["Alice", "Bob"],
            "subject_hint": "explicit",
            "predicate_family": "relationship",
            "reasoning": "relationship query",
        })

        result = await decider.evaluate(IntentDeciderInput(query="Alice和Bob什么关系"))

        assert result is not None
        assert result.entities == ["Alice", "Bob"]
        assert result.subject_hint == "explicit"
        assert result.predicate_family == "relationship"

    @pytest.mark.asyncio
    async def test_l2_semantic_frame_creator(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "B站 喜欢的 up 主",
            "entities": ["B站"],
            "subject_hint": "self",
            "predicate_family": "preference",
            "semantic_frame": {
                "query_family": "affinity",
                "subject_scope": "self",
                "answer_kind": "creator",
                "answer_unit": "identity",
                "constraints": [
                    {
                        "scope": "target",
                        "facet": "platform",
                        "raw_value": "B站",
                        "resolved_entity_id": "software:bilibili",
                    }
                ],
            },
            "reasoning": "creator affinity query",
        })

        result = await decider.evaluate(IntentDeciderInput(query="我B站喜欢哪些up主"))

        assert result is not None
        assert isinstance(result.semantic_frame, L2SemanticFrame)
        assert result.semantic_frame.answer_kind == "creator"
        assert result.semantic_frame.constraints[0].resolved_entity_id == "software:bilibili"

    @pytest.mark.asyncio
    async def test_l2_semantic_frame_place(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "杭州 喜欢去的 咖啡馆",
            "subject_hint": "self",
            "predicate_family": "preference",
            "semantic_frame": {
                "query_family": "affinity",
                "subject_scope": "self",
                "answer_kind": "place",
                "answer_unit": "place",
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
            "reasoning": "place affinity",
        })

        result = await decider.evaluate(IntentDeciderInput(query="我在杭州喜欢去哪些咖啡馆"))

        assert result is not None
        frame = result.semantic_frame
        assert isinstance(frame, L2SemanticFrame)
        assert frame.answer_kind == "place"
        assert frame.constraints[0].resolved_entity_id == "place:hangzhou"
        assert frame.constraints[1].resolved_facet_value == "coffee_shop"

    @pytest.mark.asyncio
    async def test_l2_semantic_frame_preserves_subject_roles(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "animal Nate and Joanna both like",
            "relation_intent": "likes / is fond of",
            "semantic_frame": {
                "query_family": "affinity",
                "subject_scope": "multi",
                "subject_mode": "multi",
                "relation_shape": "shared_fact",
                "subject_mentions": ["Nate", "Joanna"],
                "object_mentions": [],
                "entity_mentions": ["Nate", "Joanna"],
                "answer_kind": "topic",
                "constraints": [],
            },
            "reasoning": "shared preference query",
        })

        result = await decider.evaluate(
            IntentDeciderInput(query="What animal do both Nate and Joanna like?")
        )

        assert result is not None
        assert result.entities == ["Nate", "Joanna"]
        assert result.subject_hint == "explicit"
        assert result.predicate_family == "preference"
        frame = result.semantic_frame
        assert isinstance(frame, L2SemanticFrame)
        assert frame.subject_scope == "multi"
        assert frame.subject_mode == "multi"
        assert frame.relation_shape == "shared_fact"
        assert frame.subject_mentions == ["Nate", "Joanna"]

    @pytest.mark.asyncio
    async def test_invalid_subject_hint_dropped(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "x",
            "subject_hint": "garbage_value",
            "reasoning": "ok",
        })
        result = await decider.evaluate(IntentDeciderInput(query="x"))
        assert result is not None
        assert result.subject_hint is None

    @pytest.mark.asyncio
    async def test_invalid_predicate_family_dropped(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({
            "content_query": "x",
            "predicate_family": "weird",
            "reasoning": "ok",
        })
        result = await decider.evaluate(IntentDeciderInput(query="x"))
        assert result is not None
        assert result.predicate_family is None


# -----------------------------------------------------------------------
# Failure modes → returns None
# -----------------------------------------------------------------------


class TestLLMFailures:
    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.side_effect = TimeoutError("timeout")
        result = await decider.evaluate(IntentDeciderInput(query="hello"))
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = "not valid json at all"
        result = await decider.evaluate(IntentDeciderInput(query="hello"))
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_object_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({})
        result = await decider.evaluate(IntentDeciderInput(query="hello"))
        assert result is None

    @pytest.mark.asyncio
    async def test_no_useful_fields_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        # content_query empty + no entities + no semantic_frame → nothing useful
        mock_bridge.chat.return_value = json.dumps({"reasoning": "no info"})
        result = await decider.evaluate(IntentDeciderInput(query="hello"))
        assert result is None

    @pytest.mark.asyncio
    async def test_non_dict_response_returns_none(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps(["not", "an", "object"])
        result = await decider.evaluate(IntentDeciderInput(query="hello"))
        assert result is None


# -----------------------------------------------------------------------
# LLM call parameters
# -----------------------------------------------------------------------


class TestLLMCallParams:
    @pytest.mark.asyncio
    async def test_chat_called_with_correct_params(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})

        await decider.evaluate(IntentDeciderInput(query="test query"))

        mock_bridge.chat.assert_called_once()
        call_kwargs = mock_bridge.chat.call_args
        assert call_kwargs.kwargs["max_tokens"] == 512
        assert call_kwargs.kwargs["temperature"] == 0.3
        assert call_kwargs.kwargs["disable_thinking"] is True
        assert call_kwargs.kwargs["json_mode"] is True
        assert call_kwargs.kwargs["timeout_seconds"] == 3.0
        assert "test query" in call_kwargs.kwargs["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_chat_prompt_includes_query_mode_hint(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})

        await decider.evaluate(IntentDeciderInput(query="hello", query_mode_hint="exact_fact"))

        prompt = mock_bridge.chat.call_args.kwargs["messages"][0]["content"]
        assert "exact_fact" in prompt

    @pytest.mark.asyncio
    async def test_system_prompt_omits_layers_array(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})

        await decider.evaluate(IntentDeciderInput(query="hello"))

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        # The new contract no longer asks the LLM to produce a "layers" array.
        assert '"layers"' not in system_prompt
        # And it explicitly tells the LLM that layer routing is handled elsewhere.
        assert "Layer routing is handled elsewhere" in system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_preserves_quoted_titles_guidance(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})

        await decider.evaluate(IntentDeciderInput(query="x"))

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        assert "Keep quoted titles verbatim" in system_prompt

    @pytest.mark.asyncio
    async def test_system_prompt_describes_semantic_frame_contract(self, decider: LLMIntentDecider, mock_bridge):
        mock_bridge.chat.return_value = json.dumps({"content_query": "x", "reasoning": "ok"})

        await decider.evaluate(IntentDeciderInput(query="我喜欢什么天气"))

        system_prompt = mock_bridge.chat.call_args.kwargs["system_prompt"]
        assert "semantic_frame is authoritative" in system_prompt
        assert "subject_mode" in system_prompt
        assert "relation_shape" in system_prompt
        assert "semantic_frame" in system_prompt
        assert "answer_kind" in system_prompt


# -----------------------------------------------------------------------
# apply(): overlays refinement onto rule-routed plans
# -----------------------------------------------------------------------


class TestApplyRefinement:
    def test_overlays_content_query_on_l1_plan(self, decider: LLMIntentDecider):
        rule_decision = _make_l1_rule_plan(query="raw user query")
        refinement = LLMRefinement(content_query="refined query", reasoning="r")

        result = decider.apply(
            original_query="raw user query",
            rule_decision=rule_decision,
            refinement=refinement,
        )

        assert result.plans[0].conditions.content_query == "refined query"
        assert result.source == "llm"
        assert "llm: r" in result.reasoning

    def test_overlays_l2_fields_on_l2_plan(self, decider: LLMIntentDecider):
        rule_decision = _make_l2_rule_plan(query="原始查询")
        refinement = LLMRefinement(
            content_query="精炼查询",
            entities=["Alice"],
            subject_hint="explicit",
            predicate_family="relationship",
            reasoning="r",
        )

        result = decider.apply(
            original_query="原始查询",
            rule_decision=rule_decision,
            refinement=refinement,
        )

        l2_conditions = result.plans[0].conditions
        assert isinstance(l2_conditions, L2Conditions)
        assert l2_conditions.content_query == "精炼查询"
        assert l2_conditions.entities == ["Alice"]
        assert l2_conditions.subject_hint == "explicit"
        assert l2_conditions.predicate_family == "relationship"

    def test_overlays_semantic_frame_on_l2_plan(self, decider: LLMIntentDecider):
        rule_decision = _make_l2_rule_plan(query="x")
        frame = L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind="creator",
            answer_unit="identity",
        )
        refinement = LLMRefinement(content_query="y", semantic_frame=frame, reasoning="r")

        result = decider.apply(
            original_query="x", rule_decision=rule_decision, refinement=refinement,
        )

        l2_conditions = result.plans[0].conditions
        assert isinstance(l2_conditions, L2Conditions)
        assert l2_conditions.semantic_frame is frame

    def test_derives_l2_flat_fields_from_semantic_frame(self, decider: LLMIntentDecider):
        rule_decision = _make_l2_rule_plan(query="What animal do both Nate and Joanna like?")
        frame = L2SemanticFrame(
            query_family="affinity",
            subject_scope="multi",
            subject_mode="multi",
            relation_shape="shared_fact",
            subject_mentions=["Nate", "Joanna"],
            object_mentions=[],
            entity_mentions=["Nate", "Joanna"],
            answer_kind="topic",
        )
        refinement = LLMRefinement(
            content_query="animal Nate and Joanna both like",
            semantic_frame=frame,
            reasoning="r",
        )

        result = decider.apply(
            original_query="What animal do both Nate and Joanna like?",
            rule_decision=rule_decision,
            refinement=refinement,
        )

        l2_conditions = result.plans[0].conditions
        assert isinstance(l2_conditions, L2Conditions)
        assert l2_conditions.entities == ["Nate", "Joanna"]
        assert l2_conditions.subject_hint == "explicit"
        assert l2_conditions.predicate_family == "preference"

    def test_l3_l4_get_content_query_only(self, decider: LLMIntentDecider):
        rule_decision = IntentDecision(
            plans=[
                LayerQueryPlan(layer="L3", conditions=L3Conditions(content_query="orig")),
                LayerQueryPlan(layer="L4", conditions=L4Conditions(content_query="orig")),
            ],
            reasoning="rule",
            source="rule",
        )
        refinement = LLMRefinement(
            content_query="refined",
            entities=["should_not_apply"],
            reasoning="r",
        )

        result = decider.apply(
            original_query="orig", rule_decision=rule_decision, refinement=refinement,
        )

        assert result.plans[0].conditions.content_query == "refined"
        assert result.plans[1].conditions.content_query == "refined"

    def test_l1_validation_rejects_overly_broad_quoted_query(self, decider: LLMIntentDecider):
        original_query = (
            "How many days before the team meeting did I attend the workshop on "
            "'Effective Communication in the Workplace'?"
        )
        rule_decision = _make_l1_rule_plan(query=original_query)
        refinement = LLMRefinement(
            content_query="communication skills workshop and meeting preparation",
            reasoning="bad",
        )

        result = decider.apply(
            original_query=original_query,
            rule_decision=rule_decision,
            refinement=refinement,
        )

        # L1 validation rolls overly-broad refinement back to original_query.
        assert result.plans[0].conditions.content_query == original_query

    def test_l1_validation_rejects_overly_broad_comparison_query(self, decider: LLMIntentDecider):
        original_query = "Which vehicle did I take care of first in February, the bike or the car?"
        rule_decision = _make_l1_rule_plan(query=original_query)
        refinement = LLMRefinement(
            content_query="vehicle maintenance in february",
            reasoning="bad",
        )

        result = decider.apply(
            original_query=original_query,
            rule_decision=rule_decision,
            refinement=refinement,
        )

        assert result.plans[0].conditions.content_query == original_query

    def test_l1_validation_preserves_specific_anchor_queries(self, decider: LLMIntentDecider):
        original_query = (
            "Which event did I attend first, the 'Effective Time Management' workshop or "
            "the 'Data Analysis using Python' webinar?"
        )
        rule_decision = _make_l1_rule_plan(query=original_query)
        refinement = LLMRefinement(
            content_query="Effective Time Management workshop",
            reasoning="ok",
        )

        result = decider.apply(
            original_query=original_query,
            rule_decision=rule_decision,
            refinement=refinement,
        )

        # Refinement preserves a quoted span → kept.
        assert result.plans[0].conditions.content_query == "Effective Time Management workshop"

    def test_empty_content_query_keeps_rule_query_for_l1(self, decider: LLMIntentDecider):
        rule_decision = _make_l1_rule_plan(query="rule query")
        refinement = LLMRefinement(content_query="", entities=["X"], reasoning="r")

        result = decider.apply(
            original_query="rule query",
            rule_decision=rule_decision,
            refinement=refinement,
        )

        assert result.plans[0].conditions.content_query == "rule query"
