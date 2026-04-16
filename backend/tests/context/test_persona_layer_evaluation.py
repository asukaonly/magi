"""Tests for persona layer evaluation in PromptContextAssembler."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.context.assembler import PromptContextAssembler


def _make_persona_layer(
    layer_id: str,
    *,
    trust_gte: float = 0.0,
    interaction_gte: int = 0,
    milestone_required: str | None = None,
    persona_override: dict | None = None,
    behavior_hints: list | None = None,
) -> MagicMock:
    layer = MagicMock()
    layer.layer_id = layer_id
    condition: Dict[str, Any] = {}
    if trust_gte:
        condition["trust_level_gte"] = trust_gte
    if interaction_gte:
        condition["interaction_count_gte"] = interaction_gte
    if milestone_required:
        condition["milestone_required"] = milestone_required
    layer.unlock_condition = condition if condition else None
    layer.persona_override = persona_override
    layer.behavior_hints = behavior_hints
    return layer


def _make_self_memory(
    persona_layers: list,
    trust_level: float = 0.0,
    total_interactions: int = 0,
    milestone_titles: List[str] | None = None,
) -> MagicMock:
    config = MagicMock()
    config.persona_layers = persona_layers

    memory = MagicMock()
    memory.get_core_personality = AsyncMock(return_value=config)
    memory.get_relationship = AsyncMock(
        return_value={
            "trust_level": trust_level,
            "total_interactions": total_interactions,
        }
    )
    milestones = [{"title": t} for t in (milestone_titles or [])]
    memory.get_milestones = AsyncMock(return_value=milestones)
    return memory


class TestEvaluatePersonaLayers:
    @pytest.mark.asyncio
    async def test_no_memory_returns_empty(self):
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=None, user_id="user1"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_surface_layer_skipped(self):
        layers = [_make_persona_layer("surface")]
        memory = _make_self_memory(layers)
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_crack_unlocked_by_trust(self):
        layers = [
            _make_persona_layer(
                "crack",
                trust_gte=0.45,
                interaction_gte=5,
                persona_override={"tone_shift": "warmer"},
                behavior_hints=["be more open"],
            ),
        ]
        memory = _make_self_memory(
            layers, trust_level=0.50, total_interactions=10
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert len(result) == 1
        assert result[0]["layer_id"] == "crack"
        assert result[0]["persona_override"] == {"tone_shift": "warmer"}
        assert result[0]["behavior_hints"] == ["be more open"]

    @pytest.mark.asyncio
    async def test_crack_blocked_by_low_trust(self):
        layers = [
            _make_persona_layer("crack", trust_gte=0.45, interaction_gte=5),
        ]
        memory = _make_self_memory(
            layers, trust_level=0.30, total_interactions=10
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_revealed_blocked_without_milestone(self):
        layers = [
            _make_persona_layer(
                "revealed",
                trust_gte=0.75,
                interaction_gte=20,
                milestone_required="seven_guard_down",
            ),
        ]
        memory = _make_self_memory(
            layers, trust_level=0.80, total_interactions=50
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_revealed_unlocked_with_milestone(self):
        layers = [
            _make_persona_layer(
                "revealed",
                trust_gte=0.75,
                interaction_gte=20,
                milestone_required="seven_guard_down",
                persona_override={"vulnerability": "high"},
            ),
        ]
        memory = _make_self_memory(
            layers,
            trust_level=0.80,
            total_interactions=50,
            milestone_titles=["seven_guard_down"],
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert len(result) == 1
        assert result[0]["layer_id"] == "revealed"

    @pytest.mark.asyncio
    async def test_multiple_layers_unlocked(self):
        layers = [
            _make_persona_layer("surface"),
            _make_persona_layer(
                "crack", trust_gte=0.45, interaction_gte=5,
                persona_override={"tone": "softer"},
            ),
            _make_persona_layer(
                "revealed",
                trust_gte=0.75,
                interaction_gte=20,
                milestone_required="alan_depth_reached",
                persona_override={"vulnerability": "high"},
            ),
        ]
        memory = _make_self_memory(
            layers,
            trust_level=0.80,
            total_interactions=50,
            milestone_titles=["alan_depth_reached"],
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert len(result) == 2
        layer_ids = [r["layer_id"] for r in result]
        assert "crack" in layer_ids
        assert "revealed" in layer_ids

    @pytest.mark.asyncio
    async def test_revealed_blocked_by_interaction_count(self):
        layers = [
            _make_persona_layer(
                "revealed",
                trust_gte=0.75,
                interaction_gte=20,
                milestone_required="kai_trust_earned",
            ),
        ]
        memory = _make_self_memory(
            layers,
            trust_level=0.80,
            total_interactions=10,
            milestone_titles=["kai_trust_earned"],
        )
        assembler = PromptContextAssembler.__new__(PromptContextAssembler)
        result = await assembler._evaluate_persona_layers(
            self_memory=memory, user_id="user1"
        )
        assert result == []
