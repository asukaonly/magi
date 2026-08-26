"""Tests for PersonaTurnPlan rendering in PromptContextRenderer."""

from magi.context.assembler import PromptContextRenderer
from magi.context.schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RetrievalMemoryContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)
from magi.personality.turn_planner import ActivePersonaTrigger, PersonaTurnPlan


class TestPersonaTurnPlanRendering:
    def test_render_persona_turn_plan_active_trigger_only(self):
        renderer = PromptContextRenderer()
        plan = PersonaTurnPlan(
            persona_name="Seven",
            identity_core={
                "identity_statement": "Distrusts empty systems.",
                "values_loved": ["clarity"],
                "values_rejected": ["empty ceremony"],
                "attention_biases": ["hidden assumptions"],
            },
            idiolect={
                "sentence_style": "Fast and direct.",
                "vocab_available": ["absurd"],
                "vocab_avoided": ["Dear user"],
                "structural_quirks": ["keeps casual replies short"],
            },
            register="analysis",
            register_behavior="Structure the answer and keep judgment visible.",
            quiet_hours=[{"condition": "focused_work", "clamps": {"persona_intensity_max": 1}}],
            persona_intensity=1,
            active_triggers=[
                ActivePersonaTrigger(
                    trigger_id="domain_hotzone",
                    intensity="mid",
                    behavior_shift="Increase technical judgment.",
                )
            ],
        )

        # Persona rendering is split into the stable head (identity/voice) and
        # the per-turn steer (register/triggers/clamp); join both for content.
        text = "\n".join(
            renderer._render_persona_identity(plan)
            + renderer._render_persona_turn_steer(plan)
        )

        assert "# Persona Runtime Plan" in text  # identity head
        assert "Distrusts empty systems." in text  # identity head
        assert "Candidate: analysis" in text  # turn steer
        assert "domain_hotzone" in text  # turn steer
        assert "Increase technical judgment." in text  # turn steer
        assert "focused_work" in text  # turn steer
        assert "Contextual Behavior Protocol" not in text

    def test_plan_in_full_system_prompt(self):
        ctx = PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="You are a test entity.",
                core_truths_and_boundaries="Be useful.",
            ),
            self_memory=SelfMemoryContext(
                persona_turn_plan=PersonaTurnPlan(
                    persona_name="Seven",
                    identity_core={"identity_statement": "Pinned identity."},
                    register="task",
                    register_behavior="Solve first.",
                ),
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_date="2025-01-01",
                timezone="UTC",
                os_name="Darwin",
                os_version="24.0",
                cwd="/tmp",
                agent_id="test",
                agent_type="chat",
            ),
            tool_catalog=ToolCatalogContext(),
        )

        layers = PromptContextRenderer().render_prompt_layers(ctx)
        prompt = f"{layers.system_prompt}\n{layers.working_context}"

        assert "# Persona Runtime Plan" in prompt
        assert "Pinned identity." in prompt
        assert "Solve first." in prompt
        assert "# Contextual Behavior Protocol" not in prompt

    def test_task_preference_memory_renders_as_l4_procedural_memory(self):
        ctx = PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="You are a test entity.",
                core_truths_and_boundaries="Be useful.",
            ),
            self_memory=SelfMemoryContext(
                persona_turn_plan=PersonaTurnPlan(
                    persona_name="Seven",
                    identity_core={"identity_statement": "Pinned identity."},
                    register="task",
                ),
                retrieval_memory=RetrievalMemoryContext(
                    l4_procedural_memory=[
                        {"summary": "Prefer: 改代码前先讲方案"},
                        {"summary": "Avoid: 未验证就说完成"},
                    ],
                    preference_memory={},
                ),
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_date="2025-01-01",
                timezone="UTC",
                os_name="Darwin",
                os_version="24.0",
                cwd="/tmp",
                agent_id="test",
                agent_type="chat",
            ),
            tool_catalog=ToolCatalogContext(),
        )

        prompt = PromptContextRenderer().render_prompt_layers(ctx).working_context

        assert "* Prefer: 改代码前先讲方案" in prompt
        assert "* Avoid: 未验证就说完成" in prompt
