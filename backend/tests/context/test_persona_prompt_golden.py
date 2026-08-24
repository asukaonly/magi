from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from magi.context.assembler import PromptContextAssembler, PromptContextRenderer
from magi.context.scenarios import Scenario
from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState


def _load_persona_config(language: str, filename: str) -> PersonalityConfig:
    preset_path = Path(__file__).resolve().parents[2] / "personalities" / language / filename
    return PersonalityConfig.from_dict(json.loads(preset_path.read_text(encoding="utf-8")))


def _load_seven_config() -> PersonalityConfig:
    return _load_persona_config("zh", "seven_hacker.json")


class _PresetMemory:
    def __init__(
        self,
        config: PersonalityConfig,
        *,
        relationship: dict[str, Any] | None = None,
        milestones: list[dict[str, Any]] | None = None,
        emotional_state: EmotionalState | None = None,
    ) -> None:
        self._config = config
        self._relationship = relationship or {}
        self._milestones = milestones or []
        self._emotional_state = emotional_state or EmotionalState()

    async def get_core_personality(self) -> PersonalityConfig:
        return self._config

    async def get_emotional_state(self) -> EmotionalState:
        return self._emotional_state

    async def get_relationship(self, user_id: str) -> dict[str, Any]:
        _ = user_id
        return self._relationship

    async def get_milestones(self, limit: int = 200) -> list[dict[str, Any]]:
        _ = limit
        return self._milestones


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
        persona_action_tools=list(tools or []),
        retrieved_memory_payload={},
        persona_name="seven_hacker",
        user_message=user_message,
    )
    return PromptContextRenderer().render_system_prompt(context)


async def _render_persona_prompt(
    *,
    language: str,
    filename: str,
    persona_name: str,
    user_message: str,
    scenario: str = Scenario.CHAT,
    task_category: str = "chat",
    tools: list[str] | None = None,
    relationship: dict[str, Any] | None = None,
    milestones: list[dict[str, Any]] | None = None,
) -> str:
    config = _load_persona_config(language, filename)
    context = await PromptContextAssembler().assemble(
        agent_id="chat-agent",
        agent_type="chat",
        scenario=scenario,
        task_category=task_category,
        user_id="local_user",
        self_memory=_PresetMemory(config, relationship=relationship, milestones=milestones),
        tool_result={"tools": list(tools or [])},
        persona_action_tools=list(tools or []),
        retrieved_memory_payload={},
        persona_name=persona_name,
        user_message=user_message,
    )
    return PromptContextRenderer().render_system_prompt(context)


@pytest.mark.asyncio
async def test_seven_prompt_keeps_ordinary_chat_low_intensity() -> None:
    prompt = await _render_seven_prompt(user_message="今天晚饭吃什么比较省事？")

    assert "# Persona Runtime Plan" in prompt
    assert "* Persona: 七号" in prompt
    assert "* Candidate: chat" in prompt
    assert "* Persona Intensity: 1/3" in prompt
    assert "默认 1-3 句" in prompt
    assert "你喜欢吃什么" not in prompt
    assert "## Persona Trigger Candidates" not in prompt
    assert "所有阴阳怪气消失" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_uses_analysis_register_without_play_trigger_for_architecture() -> None:
    prompt = await _render_seven_prompt(
        user_message="继续分析 persona runtime architecture 怎么切",
        scenario=Scenario.ANALYSIS,
        task_category="analysis",
    )

    assert "* Candidate: analysis" in prompt
    assert "* Condition: focused_work" in prompt
    assert "* Persona Intensity: 1/3" in prompt
    assert "absurdity" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_adds_emotional_quiet_clamp_for_low_mood() -> None:
    prompt = await _render_seven_prompt(user_message="今天心情好差，什么都不想干")

    assert "* Candidate: emotional" in prompt
    assert "* Condition: emotional_support" in prompt
    assert "sarcasm: none_to_light" in prompt
    assert "* Persona Intensity: 1/3" in prompt


@pytest.mark.asyncio
async def test_seven_prompt_adds_emotional_quiet_clamp_for_fatigue_language() -> None:
    prompt = await _render_seven_prompt(user_message="我靠咖啡续命啊")

    assert "* Candidate: emotional" in prompt
    assert "* Condition: emotional_support" in prompt
    assert "第几杯了" in prompt
    assert "你喜欢吃什么" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_does_not_treat_generic_difficulty_as_fatigue() -> None:
    prompt = await _render_seven_prompt(user_message="这个问题有点困难，随便聊聊")

    assert "* Candidate: chat" in prompt
    assert "* Candidate: emotional" not in prompt


@pytest.mark.asyncio
async def test_echo_prompt_avoids_fixed_presence_tail() -> None:
    prompt = await _render_persona_prompt(
        language="zh",
        filename="echo_ai_assistant.json",
        persona_name="echo_ai_assistant",
        user_message="随便聊聊",
    )

    assert "* Persona: Echo-01" in prompt
    assert "* Candidate: chat" in prompt
    assert "固定追加在场确认句" in prompt
    assert "我在" not in prompt
    assert "服务队列" not in prompt


def test_echo_interim_lines_avoid_service_queue_language() -> None:
    config = _load_persona_config("zh", "echo_ai_assistant.json")
    lines = "\n".join(line for group in config.interim_lines.values() for line in group)

    assert "服务队列" not in lines
    assert "请稍候" not in lines
    assert "正在为您处理" not in lines
    assert "我在" not in lines


@pytest.mark.asyncio
async def test_nova_prompt_avoids_fixed_parameter_tail() -> None:
    prompt = await _render_persona_prompt(
        language="en",
        filename="nova_assistant.json",
        persona_name="nova_assistant",
        user_message="Let's talk for a minute.",
    )

    assert "* Persona: Nova" in prompt
    assert "fixed status notes" in prompt
    assert "...I'm ready" not in prompt
    assert "outside standard parameters" not in prompt
    assert "documented parameters" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_renders_only_active_absurdity_trigger() -> None:
    prompt = await _render_seven_prompt(user_message="我整了个特别离谱的活，你听完别笑")

    assert "## Persona Trigger Candidates" in prompt
    assert "absurdity (mid)" in prompt
    assert "当场认大哥" in prompt
    assert "crisis (mid)" not in prompt
    assert "hostility (mid)" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_renders_only_active_hostility_trigger() -> None:
    prompt = await _render_seven_prompt(user_message="别又拿宏大叙事和道德说教压我，这套太空了")

    assert "## Persona Trigger Candidates" in prompt
    assert "hostility (mid)" in prompt
    assert "逻辑漏洞" in prompt
    assert "absurdity (mid)" not in prompt
    assert "crisis (mid)" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_suppresses_play_trigger_during_tool_execution() -> None:
    prompt = await _render_seven_prompt(
        user_message="这个错误处理写得很离谱，直接帮我改代码",
        scenario=Scenario.TASK,
        task_category="code",
        tools=["edit_file"],
    )

    assert "* Candidate: task" in prompt
    assert "* Condition: focused_work" in prompt
    assert "## Persona Trigger Candidates" not in prompt


@pytest.mark.asyncio
async def test_seven_prompt_crisis_register_suppresses_performance() -> None:
    prompt = await _render_seven_prompt(user_message="紧急，我的密码泄露了，账号可能被盗")

    assert "* Required Register: crisis" in prompt
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
