"""Tests for persona journal rendering in PromptContextRenderer."""

import pytest

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


class TestPersonaJournalRendering:


    @pytest.mark.parametrize(
        "entries",
        [
            [],
            [
                {"content": "Had a meaningful conversation today.", "timestamp": 1700000000.0},
                {"content": "Noticed the user is more relaxed lately.", "timestamp": 1700086400.0},
            ],
        ],
    )
    def test_journal_renders_only_in_dynamic_layer(self, entries):
        """Journal entries should appear after persona plan rendering."""
        ctx = PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="System def",
                core_truths_and_boundaries="Boundaries",
            ),
            self_memory=SelfMemoryContext(
                persona_turn_plan=PersonaTurnPlan(
                    persona_name="Kai",
                    identity_core={"identity_statement": "A focused test persona."},
                    register="chat",
                ),
                persona_journal_entries=entries,
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_date="2024-01-01",
                timezone="UTC",
                os_name="Darwin",
                os_version="23.0",
                cwd="/tmp",
                agent_id="agent-1",
                agent_type="chat",
            ),
            tool_catalog=ToolCatalogContext(),
        )

        renderer = PromptContextRenderer()
        layers = renderer.render_prompt_layers(ctx)
        prompt = layers.working_context

        assert "Persona Runtime Plan" in layers.system_prompt
        assert SYSTEM_PROMPT_CACHE_BOUNDARY in layers.system_prompt
        assert "Internal Reflections" not in layers.system_prompt
        if not entries:
            assert "Internal Reflections" not in prompt
            return
        assert "Internal Reflections" in prompt and "System Notice" in prompt
        for entry in entries:
            assert entry["content"] in prompt
            assert entry["content"] not in layers.system_prompt
        assert prompt.index("Internal Reflections") < prompt.index("Memory Library")

    def test_skips_entries_without_content(self):
        renderer = PromptContextRenderer()
        entries = [
            {"content": "", "timestamp": 1700000000.0},
            {"content": "Valid entry.", "timestamp": 1700086400.0},
        ]

        lines = renderer._render_persona_journal(entries)
        text = "\n".join(lines)

        assert "Valid entry." in text
        # Empty content entry should be skipped, so no extra empty bold-date lines
        formatted_lines = [line for line in lines if line.startswith("**")]
        assert len(formatted_lines) == 1
