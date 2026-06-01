"""Register-conditional suppression of the 'You MUST use tools' block.

Today's case showed task-execution framing leaking into emotional turns:
the renderer unconditionally appended "## Tool Usage Instructions" with
"you MUST use the available tools to complete the user's task" whenever
any tool was selected. In emotional / crisis registers that framing
pushes the model into solve-the-problem mode and skips the acknowledgement
the user actually needed. The tool catalog itself stays visible so the
model can still call tools when they are genuinely useful; only the
imperative framing gets dropped.
"""

from __future__ import annotations

from typing import Any

import pytest

from magi.context.assembler import PromptContextAssembler, PromptContextRenderer
from magi.context.scenarios import Scenario
from magi.personality.loader import PersonalityConfig, Register
from magi.personality.turn_planner import PersonaRoutingHint


class _StubMemory:
    personality_name = "stub"

    def __init__(self, register_examples: list[str] | None = None) -> None:
        self._config = PersonalityConfig(
            name="stub",
            registers={
                "chat": Register(description="chat", behavior="chat"),
                "emotional": Register(description="emo", behavior="emo"),
                "crisis": Register(description="crisis", behavior="crisis"),
                "task": Register(description="task", behavior="task"),
            },
        )

    async def get_core_personality(self) -> PersonalityConfig:
        return self._config

    async def get_emotional_state(self) -> Any:
        return None

    async def get_relationship(self, user_id: str) -> dict[str, Any]:
        return {}

    async def get_milestones(self, limit: int = 200) -> list[dict[str, Any]]:
        return []


async def _render_with(
    scenario: str,
    task_category: str,
    user_message: str,
    tools: list[str],
    *,
    routing_hint: PersonaRoutingHint | None = None,
) -> str:
    context = await PromptContextAssembler().assemble(
        agent_id="chat-agent",
        agent_type="chat",
        scenario=scenario,
        task_category=task_category,
        user_id="local_user",
        self_memory=_StubMemory(),
        tool_result={"tools": tools},
        retrieved_memory_payload={},
        persona_name="stub",
        user_message=user_message,
        persona_routing_hint=routing_hint,
    )
    return PromptContextRenderer().render_system_prompt(context)


@pytest.mark.asyncio
async def test_task_register_keeps_tool_imperatives() -> None:
    prompt = await _render_with(
        scenario=Scenario.TASK,
        task_category="code",
        user_message="帮我修这个 bug",
        tools=["edit_file"],
    )
    assert "## Tool Usage Instructions" in prompt
    assert "You MUST use the available tools" in prompt
    assert "* edit_file" in prompt  # catalog still rendered


@pytest.mark.asyncio
async def test_emotional_register_drops_tool_imperatives_but_keeps_catalog() -> None:
    # Pin register via routing_hint — the keyword fallback would otherwise
    # see non-empty tools and force task. In production the LLM router
    # (ContextDecider) is what supplies the hint and overrides keywords.
    prompt = await _render_with(
        scenario=Scenario.CHAT,
        task_category="chat",
        user_message="今天心情真的好差，什么都不想干",
        tools=["web-search"],
        routing_hint=PersonaRoutingHint(register="emotional"),
    )
    # Imperatives gone — model is not pushed into task-execution mode.
    assert "## Tool Usage Instructions" not in prompt
    assert "You MUST use the available tools" not in prompt
    # Catalog still listed so the tool remains callable if genuinely needed.
    assert "* web-search" in prompt


@pytest.mark.asyncio
async def test_crisis_register_drops_tool_imperatives_but_keeps_catalog() -> None:
    prompt = await _render_with(
        scenario=Scenario.CHAT,
        task_category="chat",
        user_message="紧急，我密码泄露了",
        tools=["memory_query"],
        routing_hint=PersonaRoutingHint(register="crisis"),
    )
    assert "## Tool Usage Instructions" not in prompt
    assert "* memory_query" in prompt


@pytest.mark.asyncio
async def test_casual_register_keeps_tool_imperatives() -> None:
    """Casual chat may still need tools (e.g. quick 'what's the weather'),
    so the imperative block stays — only emotional / crisis suppress it."""
    prompt = await _render_with(
        scenario=Scenario.CHAT,
        task_category="chat",
        user_message="今天天气怎么样",
        tools=["web-search"],
        routing_hint=PersonaRoutingHint(register="casual"),
    )
    assert "## Tool Usage Instructions" in prompt


@pytest.mark.asyncio
async def test_empty_tool_catalog_never_renders_imperatives() -> None:
    prompt = await _render_with(
        scenario=Scenario.CHAT,
        task_category="chat",
        user_message="随便聊聊",
        tools=[],
    )
    assert "## Tool Usage Instructions" not in prompt
