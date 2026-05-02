from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from magi.context.assembler import PromptContextAssembler, PromptContextRenderer
from magi.context.scenarios import Scenario
from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState


def _load_seven_config() -> PersonalityConfig:
    preset_path = Path(__file__).resolve().parents[2] / "personalities" / "zh" / "seven_hacker.json"
    return PersonalityConfig.from_dict(json.loads(preset_path.read_text(encoding="utf-8")))


class _SevenMemory:
    personality_name = "seven_hacker"

    def __init__(
        self,
        *,
        relationship: dict[str, Any] | None = None,
        milestones: list[dict[str, Any]] | None = None,
        emotional_state: EmotionalState | None = None,
    ) -> None:
        self._relationship = relationship or {}
        self._milestones = milestones or []
        self._emotional_state = emotional_state or EmotionalState()

    async def get_core_personality(self) -> PersonalityConfig:
        return _load_seven_config()

    async def get_emotional_state(self) -> EmotionalState:
        return self._emotional_state

    async def get_relationship(self, user_id: str) -> dict[str, Any]:
        _ = user_id
        return self._relationship

    async def get_milestones(self, limit: int = 200) -> list[dict[str, Any]]:
        _ = limit
        return self._milestones


async def _render_seven_prompt(
    *,
    user_message: str,
    scenario: str = Scenario.CHAT,
    task_category: str = "chat",
    tools: list[str] | None = None,
    relationship: dict[str, Any] | None = None,
    milestones: list[dict[str, Any]] | None = None,
) -> str:
    context = await PromptContextAssembler().assemble(
        agent_id="chat-agent",
        agent_type="chat",
        scenario=scenario,
        task_category=task_category,
        user_id="local_user",
        self_memory=_SevenMemory(relationship=relationship, milestones=milestones),
        tool_result={"tools": list(tools or [])},
        retrieved_memory_payload={},
        persona_name="seven_hacker",
        user_message=user_message,
    )
    return PromptContextRenderer().render_system_prompt(context)


@pytest.mark.asyncio
async def test_seven_prompt_keeps_ordinary_chat_low_intensity() -> None:
    prompt = await _render_seven_prompt(user_message="今天晚饭吃什么比较省事？")

    assert "# Persona Runtime Plan" in prompt
    assert "* Persona: 七号" in prompt
    assert "* Register: chat" in prompt
    assert "* Persona Intensity: 1/3" in prompt
    assert "## Active Persona Triggers" not in prompt
    assert "所有阴阳怪气消失" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_uses_analysis_register_without_play_trigger_for_architecture() -> None:
    prompt = await _render_seven_prompt(
        user_message="继续分析 persona runtime architecture 怎么切",
        scenario=Scenario.ANALYSIS,
        task_category="analysis",
    )

    assert "* Register: analysis" in prompt
    assert "* Condition: focused_work" in prompt
    assert "* Persona Intensity: 1/3" in prompt
    assert "absurdity" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_adds_emotional_quiet_clamp_for_low_mood() -> None:
    prompt = await _render_seven_prompt(user_message="今天心情好差，什么都不想干")

    assert "* Register: emotional" in prompt
    assert "* Condition: emotional_support" in prompt
    assert "sarcasm: none_to_light" in prompt
    assert "* Persona Intensity: 1/3" in prompt


@pytest.mark.asyncio
async def test_seven_prompt_renders_only_active_absurdity_trigger() -> None:
    prompt = await _render_seven_prompt(user_message="我整了个特别离谱的活，你听完别笑")

    assert "## Active Persona Triggers" in prompt
    assert "absurdity (mid)" in prompt
    assert "当场认大哥" in prompt
    assert "crisis (mid)" not in prompt
    assert "hostility (mid)" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_crisis_register_suppresses_performance() -> None:
    prompt = await _render_seven_prompt(user_message="紧急，我的密码泄露了，账号可能被盗")

    assert "* Register: crisis" in prompt
    assert "* Persona Intensity: 0/3" in prompt
    assert "* Condition: crisis" in prompt
    assert "sarcasm: none" in prompt
    assert "crisis (mid)" in prompt


@pytest.mark.asyncio
async def test_seven_prompt_revealed_layer_renders_relationship_modifiers() -> None:
    prompt = await _render_seven_prompt(
        user_message="随便聊聊",
        relationship={"trust_level": 0.8, "total_interactions": 80},
        milestones=[{"key": "seven_guard_down"}],
    )

    assert "## Relationship Layer Modifiers" in prompt
    assert "* Active Layer: revealed" in prompt
    assert "护短" in prompt
