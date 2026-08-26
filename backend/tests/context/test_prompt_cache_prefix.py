"""Prompt-cache prefix-stability tests (issue #97).

Prompt caching on every provider is a prefix match: any byte that changes
between consecutive requests invalidates the cache from that point onward.
These tests pin the prefix-stabilising guarantees for prompt layers:

1. Static blocks (identity + persona definition) render only in the system
   layer; run-local and host-state inputs render in separate typed layers.
2. The tool list — both the wire ``tools`` parameter and the in-prompt tool
   guidance — does not duplicate tool names/descriptions in the prompt. The
   wire ``tools`` parameter remains deterministic, name-sorted output.
3. Changing the selected tool SET does not change the cacheable system head.
"""

from __future__ import annotations

from magi.agent.execution.function_calling.tools import build_tools_parameter
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


def _assembly_context(selected_tools: list[str]) -> PromptAssemblyContext:
    return PromptAssemblyContext(
        identity_constraints=IdentityConstraintContext(
            system_definition="You are a test entity.",
            core_truths_and_boundaries="Be useful.",
        ),
        self_memory=SelfMemoryContext(
            persona_turn_plan=PersonaTurnPlan(
                persona_name="Seven",
                identity_core={"identity_statement": "Pinned identity."},
                idiolect={"sentence_style": "terse"},
                register="task",
                register_behavior="Be direct.",
                dynamic_modulations={"low_energy": "shorter replies"},
                selected_examples=["[User: hi]\nSeven: yo"],
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
        tool_catalog=ToolCatalogContext(selected_tools=selected_tools),
    )


def test_static_and_dynamic_blocks_render_in_separate_layers() -> None:
    layers = PromptContextRenderer().render_prompt_layers(
        _assembly_context(["alpha_tool"])
    )

    assert layers.system_prompt.index("# System Definition") < layers.system_prompt.index(
        "# Persona Runtime Plan"
    )
    assert layers.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert "# Tool Use Guidance" not in layers.system_prompt
    assert "# Memory Library" not in layers.system_prompt
    assert "# Runtime World State" not in layers.system_prompt
    assert layers.working_context.index("# Tool Use Guidance") < layers.working_context.index(
        "# Memory Library"
    )
    assert "# Runtime World State" in layers.runtime_world_state


def test_cache_boundary_sits_after_persona_identity_before_dynamic() -> None:
    layers = PromptContextRenderer().render_prompt_layers(
        _assembly_context(["alpha_tool"])
    )

    assert layers.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert layers.system_prompt.index("# Persona Runtime Plan") < layers.system_prompt.index(
        SYSTEM_PROMPT_CACHE_BOUNDARY
    )
    assert "# Tool Use Guidance" in layers.working_context
    assert "# Memory Library" in layers.working_context
    assert "# Runtime World State" in layers.runtime_world_state


def test_selected_tool_changes_do_not_change_cacheable_head() -> None:
    layers_a = PromptContextRenderer().render_prompt_layers(
        _assembly_context(["alpha_tool"])
    )
    layers_b = PromptContextRenderer().render_prompt_layers(
        _assembly_context(["beta_tool"])
    )

    assert layers_a.system_prompt == layers_b.system_prompt
    assert "alpha_tool" not in layers_a.system_prompt
    assert "beta_tool" not in layers_b.system_prompt
    assert "alpha_tool" not in layers_a.working_context
    assert "beta_tool" not in layers_b.working_context
    assert layers_a.working_context == layers_b.working_context


def test_profile_memory_prefers_prompt_summary_over_raw_preferences() -> None:
    context = _assembly_context(["alpha_tool"])
    context.profile_memory = ProfileMemoryContext(
        user_id="u1",
        user_preferences={
            "interest.rag": {
                "value": "RAG",
                "affinity": 1.0,
                "family": "preference_profile",
                "source_tier": "inferred",
            }
        },
        prompt_summary=[
            "用户长期关注 Magi 记忆系统和 RAG。",
            "用户偏好先讲结论，再补关键依据。",
        ],
    )

    prompt = PromptContextRenderer().render_prompt_layers(context).working_context

    assert "# User Understanding" in prompt
    assert "用户长期关注 Magi 记忆系统和 RAG。" in prompt
    assert "用户偏好先讲结论，再补关键依据。" in prompt
    assert "interest.rag" not in prompt
    assert "affinity" not in prompt
    assert "source_tier" not in prompt


def test_profile_memory_fallback_omits_internal_profile_keys() -> None:
    context = _assembly_context(["alpha_tool"])
    context.profile_memory = ProfileMemoryContext(
        user_id="u1",
        user_name="Asuka",
        user_preferences={
            "identity.real_name": "明日香",
            "communication.address.preferred": "Asuka",
            "identity.birth_date": "2000-01-01",
            "identity.age_years": 26,
            "identity.location.home": "Hangzhou",
            "communication.address.disallowed": ["老师"],
            "interest.rag": {
                "value": "RAG",
                "affinity": 1.0,
                "family": "preference_profile",
            },
        },
    )

    prompt = PromptContextRenderer().render_prompt_layers(context).working_context

    assert "Asuka" in prompt
    assert "明日香" in prompt
    assert "Hangzhou" in prompt
    assert "2000-01-01" in prompt
    assert "26" in prompt
    assert "老师" in prompt
    assert "identity.real_name" not in prompt
    assert "communication.address.preferred" not in prompt
    assert "identity.birth_date" not in prompt
    assert "identity.age_years" not in prompt
    assert "interest.rag" not in prompt
    assert "affinity" not in prompt
    assert "family" not in prompt


def test_profile_memory_recent_emotion_uses_labels_without_scores() -> None:
    context = _assembly_context(["alpha_tool"])
    context.profile_memory = ProfileMemoryContext(
        user_id="u1",
        prompt_summary=["用户偏好先讲结论。"],
        recent_emotion={
            "sentiment_score": 0.03,
            "emotion_label": "neutral",
            "trust_level": 0.55,
            "trust_label": "medium",
        },
    )

    prompt = PromptContextRenderer().render_prompt_layers(context).working_context

    assert "neutral" in prompt
    assert "medium" in prompt
    assert "score:" not in prompt
    assert "level:" not in prompt
    assert "0.03" not in prompt
    assert "0.55" not in prompt


def test_persona_identity_in_head_per_turn_steer_in_tail() -> None:
    # The persona DEFINITION (Identity Core + Baseline Voice) is stable across
    # turns and stays in the cached head. The per-turn run input (register,
    # modulation, examples) is recomputed every turn by PersonaTurnPlanner, so it
    # must sit below the boundary or it invalidates the cached prefix each turn
    # (root cause of cache read=0 on the chat path).
    layers = PromptContextRenderer().render_prompt_layers(
        _assembly_context(["alpha_tool"])
    )

    assert "## Identity Core" in layers.system_prompt
    assert "## Baseline Voice" in layers.system_prompt
    assert "## Expression Policy" not in layers.system_prompt
    assert "## Dynamic Modulation" not in layers.system_prompt
    assert "## Relevant Persona Examples" not in layers.system_prompt
    assert "## Expression Policy" in layers.working_context
    assert "## Dynamic Modulation" in layers.working_context
    assert "## Relevant Persona Examples" in layers.working_context


class _FakeToolRegistry:
    def is_skill(self, name: str) -> bool:  # noqa: D401 - test stub
        return False

    def get_tool_info(self, name: str) -> dict:
        return {"description": f"desc-{name}", "parameters": []}


def test_build_tools_parameter_order_is_name_stable() -> None:
    registry = _FakeToolRegistry()

    out_a = build_tools_parameter(registry, ["zebra", "alpha", "mango"])
    out_b = build_tools_parameter(registry, ["alpha", "mango", "zebra"])

    names_a = [tool["function"]["name"] for tool in out_a]
    assert names_a == ["alpha", "mango", "zebra"]
    # Same SET in a different upstream order must serialise identically.
    assert out_a == out_b


def test_tool_guidance_omits_tool_names_and_catalog_descriptions() -> None:
    renderer = PromptContextRenderer()
    catalog = ToolCatalogContext(selected_tools=["zebra", "alpha"])

    text = "\n".join(renderer._render_tool_catalog(catalog))

    assert "# Tool Use Guidance" in text
    assert "Selected Tools" not in text
    assert "Tool Catalog" not in text
    assert "alpha" not in text
    assert "zebra" not in text
    assert "description" not in text
