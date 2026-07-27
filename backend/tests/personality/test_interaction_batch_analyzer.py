"""Tests for shared post-turn batch understanding."""

from __future__ import annotations

import json

import pytest

from magi.memory.l0.attention_update_scheduler import AcceptedL0AttentionTurn
from magi.personality import interaction_batch_analyzer as subject


def _turn(turn_id: str) -> AcceptedL0AttentionTurn:
    return AcceptedL0AttentionTurn(
        user_id="user-1",
        session_id="session-1",
        turn_id=turn_id,
        user_message=f"用户消息 {turn_id}",
        assistant_response=f"回复 {turn_id}",
        epoch=1,
    )


def test_parse_batch_constrains_turns_observations_and_attention_targets() -> None:
    batch = (_turn("turn-1"), _turn("turn-2"))
    raw = json.dumps(
        {
            "turns": [
                {
                    "turn_id": "turn-1",
                    "sentiment": 0.5,
                    "engagement": "high",
                    "complexity": 0.7,
                    "outcome": "success",
                    "satisfaction": "high",
                    "memory_observations": [
                        {
                            "kind": "profile_signal",
                            "arguments": {
                                "trait_family": "communication_profile",
                                "trait_name": "style",
                                "trait_value": "direct",
                                "evidence_text": "用户消息 turn-1",
                                "confidence": 0.9,
                            },
                        }
                    ],
                },
                {
                    "turn_id": "unknown",
                    "sentiment": -1,
                    "engagement": "none",
                    "complexity": 0,
                    "outcome": "failure",
                    "satisfaction": "very_low",
                },
            ],
            "attention_actions": [
                {
                    "action": "reinforce",
                    "target_item_id": "attention-existing",
                    "summary": "继续讨论现有关注",
                    "salience": 0.9,
                    "confidence": 0.9,
                    "evidence_mode": "direct",
                    "source_turn_ids": ["turn-1", "unknown"],
                },
                {
                    "action": "resolve",
                    "target_item_id": "attention-missing",
                    "source_turn_ids": ["turn-1"],
                },
            ],
        }
    )

    parsed = subject.parse_interaction_batch(
        raw,
        batch=batch,
        current_attention=[{"item_id": "attention-existing"}],
    )

    assert parsed is not None
    assert list(parsed.turn_analyses) == ["turn-1", "turn-2"]
    assert parsed.turn_analyses["turn-1"].satisfaction.value == "high"
    assert len(parsed.turn_analyses["turn-1"].memory_observations) == 1
    assert parsed.turn_analyses["turn-2"] is subject.DEFAULT_ANALYSIS
    assert len(parsed.attention_actions) == 1
    assert parsed.attention_actions[0].source_turn_ids == ("turn-1",)


def test_parse_batch_rejects_raw_or_unproven_attention_actions() -> None:
    batch = (_turn("turn-1"),)
    raw = json.dumps(
        {
            "turns": [],
            "attention_actions": [
                {
                    "action": "add",
                    "kind": "not-a-kind",
                    "summary": "bad",
                    "source_turn_ids": ["turn-1"],
                },
                {
                    "action": "add",
                    "kind": "focus",
                    "summary": "missing provenance",
                    "source_turn_ids": None,
                },
                {
                    "action": "add",
                    "kind": "focus",
                    "summary": "保留当前关注",
                    "source_turn_ids": ["turn-1"],
                },
            ],
        }
    )

    parsed = subject.parse_interaction_batch(
        raw,
        batch=batch,
        current_attention=[],
    )

    assert parsed is not None
    assert len(parsed.attention_actions) == 1
    assert parsed.attention_actions[0].summary == "保留当前关注"


@pytest.mark.parametrize("raw_observations", [None, {}, "invalid", 1])
def test_parse_batch_ignores_non_list_memory_observations(raw_observations) -> None:
    batch = (_turn("turn-1"),)
    raw = json.dumps(
        {
            "turns": [
                {
                    "turn_id": "turn-1",
                    "sentiment": 0.0,
                    "engagement": "medium",
                    "complexity": 0.5,
                    "outcome": "success",
                    "satisfaction": "neutral",
                    "memory_observations": raw_observations,
                }
            ],
            "attention_actions": [],
        }
    )

    parsed = subject.parse_interaction_batch(
        raw,
        batch=batch,
        current_attention=[],
    )

    assert parsed is not None
    assert parsed.turn_analyses["turn-1"].memory_observations == []


def test_batch_prompt_has_a_fixed_total_turn_budget() -> None:
    batch = tuple(
        AcceptedL0AttentionTurn(
            user_id="user-1",
            session_id="session-1",
            turn_id=f"turn-{index}",
            user_message="u" * 10_000,
            assistant_response="a" * 10_000,
            epoch=1,
        )
        for index in range(20)
    )

    prompt = subject._build_batch_prompt(
        batch,
        current_attention=[],
        stp_rules=None,
        milestone_conditions=None,
    )
    payload = json.loads(prompt)
    total_turn_chars = sum(
        len(turn["user_message"]) + len(turn["assistant_response"]) for turn in payload["turns"]
    )

    assert total_turn_chars <= subject._TURN_INPUT_BUDGET_CHARS
    assert all(turn["user_message"] for turn in payload["turns"])
    assert all(turn["assistant_response"] for turn in payload["turns"])


@pytest.mark.asyncio
async def test_analyze_batch_degrades_to_noop_when_no_llm_is_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(subject, "_resolve_analysis_bridge", lambda: None)

    parsed = await subject.analyze_interaction_batch(
        (_turn("turn-1"), _turn("turn-2")),
        current_attention=[],
    )

    assert parsed is not None
    assert set(parsed.turn_analyses) == {"turn-1", "turn-2"}
    assert parsed.attention_actions == ()
