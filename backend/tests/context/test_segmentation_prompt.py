"""Inline reply-segmentation prompt injection for conversation rhythm."""

from __future__ import annotations

import magi.context.renderer as renderer_module
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.context.assembler import PromptContextRenderer
from magi.context.schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)
from magi.personality.turn_planner import PersonaTurnPlan


def _context(
    *,
    register: str = "chat",
    chattiness: float = 0.8,
    persona_intensity: int = 1,
    persona_name: str = "Seven",
) -> PromptAssemblyContext:
    return PromptAssemblyContext(
        identity_constraints=IdentityConstraintContext(
            system_definition="You are a test entity.",
            core_truths_and_boundaries="Be useful.",
        ),
        self_memory=SelfMemoryContext(
            persona_turn_plan=PersonaTurnPlan(
                persona_name=persona_name,
                identity_core={"identity_statement": "Pinned."},
                idiolect={"sentence_style": "terse", "chattiness": chattiness},
                register=register,
                persona_intensity=persona_intensity,
            ),
        ),
        profile_memory=ProfileMemoryContext(user_id="u1"),
        runtime_system=RuntimeSystemContext(
            current_date="2026-01-01",
            timezone="UTC",
            os_name="Darwin",
            os_version="24.0",
            cwd="/tmp",
            agent_id="test",
            agent_type="chat",
        ),
        tool_catalog=ToolCatalogContext(selected_tools=["alpha_tool"]),
    )


def _set_rhythm(monkeypatch, *, on: bool = True) -> None:
    def fake_get_user_preference(key, default=None):  # type: ignore[no-untyped-def]
        if key == "conversation_rhythm_enabled":
            return on
        if key == "conversation_rhythm_mode":
            return "natural" if on else "off"
        return default

    monkeypatch.setattr(renderer_module, "get_user_preference", fake_get_user_preference)


def test_segmentation_protocol_is_above_cache_boundary_and_stable(monkeypatch) -> None:
    _set_rhythm(monkeypatch)
    renderer = PromptContextRenderer()
    chat_prompt = renderer.render_prompt_layers(
        _context(register="chat", chattiness=0.9)
    ).system_prompt
    task_prompt = renderer.render_prompt_layers(
        _context(register="task", chattiness=0.1, persona_name="Other")
    ).system_prompt

    assert "# Reply Segmentation Protocol" in chat_prompt
    assert "‖" in chat_prompt
    assert chat_prompt.index("# Reply Segmentation Protocol") < chat_prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)

    def protocol_section(prompt: str) -> str:
        start = prompt.index("# Reply Segmentation Protocol")
        end = prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)
        return prompt[start:end]

    assert protocol_section(chat_prompt) == protocol_section(task_prompt)


def test_reply_pacing_is_in_working_context_and_persona_aware(monkeypatch) -> None:
    _set_rhythm(monkeypatch)
    renderer = PromptContextRenderer()
    chatty_layers = renderer.render_prompt_layers(
        _context(register="chat", chattiness=0.85)
    )
    chatty_prompt = chatty_layers.working_context
    assert "## Reply Pacing" in chatty_prompt
    assert "## Reply Pacing" not in chatty_layers.system_prompt
    assert "2-6 short bubbles" in chatty_prompt

    serious_prompt = renderer.render_prompt_layers(
        _context(register="crisis", chattiness=0.9, persona_intensity=0)
    ).working_context
    serious_pacing = serious_prompt[serious_prompt.index("## Reply Pacing"):]
    assert "one message" in serious_pacing

    reserved_prompt = renderer.render_prompt_layers(
        _context(register="chat", chattiness=0.3)
    ).working_context
    reserved_pacing = reserved_prompt[reserved_prompt.index("## Reply Pacing"):]
    assert "only split" in reserved_pacing


def test_segmentation_blocks_absent_when_rhythm_disabled(monkeypatch) -> None:
    _set_rhythm(monkeypatch, on=False)
    layers = PromptContextRenderer().render_prompt_layers(
        _context(register="chat", chattiness=0.9)
    )

    assert "# Reply Segmentation Protocol" not in layers.system_prompt
    assert "## Reply Pacing" not in layers.working_context
