"""Tests for state_transition_protocol rendering in PromptContextRenderer."""

import pytest

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
        assert "## Crisis" in text
        assert "Emergency Mode" not in text
        assert "* When: User faces an urgent emergency" in text
        assert "* Behavior: Drop all small talk, output numbered action list." in text
        assert "## Intimacy" in text
        assert "Inner Circle" not in text
        assert "Do not announce, name, or narrate state transitions" in text

    def test_render_empty_stp(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_state_transition_rules([])
        assert lines == []

    def test_render_state_override_with_behavior_shift(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_state_override("Emergency Mode", "Focus and give numbered steps.")
        text = "\n".join(lines)
        assert "Emergency Mode" not in text
        assert "Behavioral Directive: Focus and give numbered steps." in text
        assert "never mention the state name" in text

    def test_render_state_override_without_behavior_shift(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_state_override("Emergency Mode")
        text = "\n".join(lines)
        assert "Emergency Mode" not in text
        assert "Internal State: active" in text
        assert "Behavioral Directive" not in text

    def test_render_state_override_no_override(self):
        renderer = PromptContextRenderer()
        lines = renderer._render_state_override(None)
        text = "\n".join(lines)
        assert "N/A (using baseline persona)" in text

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
        assert "## Hostility" in prompt
        assert "Boundary Setting" not in prompt
        assert "Stay calm and set boundaries." in prompt


class TestStpOnDemandFiltering:
    """Verify the assembler only injects the active STP rule and sets the override."""

    @staticmethod
    def _make_config():
        from magi.personality.loader import (
            PersonalityConfig,
            StateTransitionProtocolItem,
        )
        config = PersonalityConfig()
        config.state_transition_protocol = [
            StateTransitionProtocolItem(
                trigger_type="crisis",
                trigger_condition="User faces an emergency",
                target_state_name="Emergency Mode",
                behavior_shift="Focus, give numbered steps.",
            ),
            StateTransitionProtocolItem(
                trigger_type="hostility",
                trigger_condition="User is hostile",
                target_state_name="Boundary Setting",
                behavior_shift="Stay calm.",
            ),
        ]
        return config

    @staticmethod
    def _make_emotion(trigger: str = "", state_name: str = ""):
        from magi.personality.models import EmotionalState
        return EmotionalState(
            active_stp_trigger=trigger,
            active_stp_state_name=state_name,
        )

    async def _assemble(self, trigger: str, state_name: str):
        from unittest.mock import AsyncMock
        from magi.context.assembler import PromptContextAssembler

        config = self._make_config()
        emotion = self._make_emotion(trigger, state_name)

        fake_self_memory = AsyncMock()
        fake_self_memory.get_core_personality = AsyncMock(return_value=config)
        fake_self_memory.get_emotional_state = AsyncMock(return_value=emotion)

        assembler = PromptContextAssembler(tool_registry=None)
        ctx = await assembler._build_self_memory_context(
            self_memory=fake_self_memory,
            user_id="u1",
            task_category="chat",
            retrieved_memory_payload=None,
            state_transition_override=None,
            scenario="chat",
            persona_name="test",
        )
        return ctx

    @pytest.mark.asyncio
    async def test_no_active_trigger_injects_all_rules(self):
        ctx = await self._assemble("", "")
        assert len(ctx.state_transition_rules) == 2
        assert ctx.state_transition_override is None

    @pytest.mark.asyncio
    async def test_active_trigger_filters_to_matching_rule(self):
        ctx = await self._assemble("crisis", "Emergency Mode")
        assert len(ctx.state_transition_rules) == 1
        assert ctx.state_transition_rules[0]["trigger_type"] == "crisis"
        assert ctx.state_transition_override == "Emergency Mode"
        assert ctx.state_transition_behavior_shift == "Focus, give numbered steps."

    @pytest.mark.asyncio
    async def test_active_trigger_no_match_injects_nothing(self):
        ctx = await self._assemble("absurdity", "Comedy Mode")
        # No absurdity rule in config — nothing injected.
        assert len(ctx.state_transition_rules) == 0
        assert ctx.state_transition_override == "Comedy Mode"
