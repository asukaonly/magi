"""Tests for persona journal rendering in PromptContextRenderer."""

import time

from magi.context.assembler import PromptContextRenderer
from magi.context.schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)


class TestPersonaJournalRendering:
    def test_render_journal_entries(self):
        renderer = PromptContextRenderer()
        entries = [
            {"content": "Had a meaningful conversation today.", "timestamp": 1700000000.0},
            {"content": "Noticed the user is more relaxed lately.", "timestamp": 1700086400.0},
        ]

        lines = renderer._render_persona_journal(entries)
        text = "\n".join(lines)

        assert "# Internal Reflections" in text
        assert "Had a meaningful conversation today." in text
        assert "Noticed the user is more relaxed lately." in text
        assert "System Notice" in text

    def test_render_empty_journal(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_persona_journal([])
        assert lines == []

    def test_journal_in_full_system_prompt(self):
        """Journal entries should appear between STP rules and scenario prompt."""
        ctx = PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="System def",
                core_truths_and_boundaries="Boundaries",
            ),
            self_memory=SelfMemoryContext(
                persona_entity={"basic_profile": {"name": "Kai"}},
                persona_journal_entries=[
                    {"content": "Reflected on recent growth.", "timestamp": time.time()},
                ],
                scenario_prompt="Be direct and efficient.",
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_time_iso="2024-01-01T00:00:00",
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
        prompt = renderer.render_system_prompt(ctx)

        # Journal should be present
        assert "Internal Reflections" in prompt
        assert "Reflected on recent growth." in prompt

        # Journal should come before scenario prompt
        journal_pos = prompt.index("Internal Reflections")
        scenario_pos = prompt.index("Be direct and efficient.")
        assert journal_pos < scenario_pos

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
        formatted_lines = [l for l in lines if l.startswith("**")]
        assert len(formatted_lines) == 1
