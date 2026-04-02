"""Tests for state_transition_protocol rendering in PromptContextRenderer."""

from magi.context.assembler import PromptContextRenderer
from magi.context.schema import SelfMemoryContext


class TestStateTransitionRulesRendering:
    def test_render_stp_rules(self):
        renderer = PromptContextRenderer()
        rules = [
            {
                "trigger_type": "crisis",
                "trigger_condition": "User faces an urgent emergency",
                "target_state_name": "Emergency Mode",
                "behavior_shift": "Drop all small talk, output numbered action list.",
            },
            {
                "trigger_type": "intimacy",
                "trigger_condition": "User shows deep trust",
                "target_state_name": "Inner Circle",
                "behavior_shift": "Speak more openly, share personal anecdotes.",
            },
        ]

        lines = renderer._render_state_transition_rules(rules)
        text = "\n".join(lines)

        assert "# Contextual Behavior Protocol" in text
        assert "## Crisis: Emergency Mode" in text
        assert "* When: User faces an urgent emergency" in text
        assert "* Behavior: Drop all small talk, output numbered action list." in text
        assert "## Intimacy: Inner Circle" in text

    def test_render_empty_stp(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_state_transition_rules([])
        assert lines == []

    def test_stp_in_full_system_prompt(self):
        """STP rules should appear in the final rendered system prompt."""
        from magi.context.schema import (
            IdentityConstraintContext,
            ProfileMemoryContext,
            PromptAssemblyContext,
            RuntimeSystemContext,
            ToolCatalogContext,
        )

        ctx = PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="You are a test entity.",
                core_truths_and_boundaries="Be good.",
            ),
            self_memory=SelfMemoryContext(
                persona_entity={"basic_profile": {"name": "Test"}},
                state_transition_rules=[
                    {
                        "trigger_type": "hostility",
                        "trigger_condition": "User is hostile",
                        "target_state_name": "Boundary Setting",
                        "behavior_shift": "Stay calm and set boundaries.",
                    }
                ],
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_time_iso="2025-01-01T00:00:00",
                timezone="UTC",
                os_name="Darwin",
                os_version="24.0",
                cwd="/tmp",
                agent_id="test",
                agent_type="chat",
            ),
            tool_catalog=ToolCatalogContext(),
        )

        renderer = PromptContextRenderer()
        prompt = renderer.render_system_prompt(ctx)

        assert "# Contextual Behavior Protocol" in prompt
        assert "## Hostility: Boundary Setting" in prompt
        assert "Stay calm and set boundaries." in prompt
