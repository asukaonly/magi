"""Prompt-cache prefix-stability tests (issue #97).

Prompt caching on every provider is a prefix match: any byte that changes
between consecutive requests invalidates the cache from that point onward.
These tests pin the prefix-stabilising guarantees for the system prompt:

1. Static blocks (identity + persona definition) render BEFORE the per-turn
   dynamic blocks (tool-use guidance, persona steer, memory, runtime/time) so the
   largest stable chunk sits at the front of the prefix.
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
            current_time_iso="2025-01-01T00:00:00",
            timezone="UTC",
            os_name="Darwin",
            os_version="24.0",
            cwd="/tmp",
            agent_id="test",
            agent_type="chat",
        ),
        tool_catalog=ToolCatalogContext(selected_tools=selected_tools),
    )


def _split_prompt(prompt: str) -> tuple[str, str]:
    assert SYSTEM_PROMPT_CACHE_BOUNDARY in prompt
    head, _, tail = prompt.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    return head, tail


def test_static_blocks_render_before_dynamic_blocks() -> None:
    prompt = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))

    i_definition = prompt.index("# System Definition")
    i_tools = prompt.index("# Tool Use Guidance")
    i_persona = prompt.index("# Persona Runtime Plan")
    i_boundary = prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)
    i_memory = prompt.index("# Memory Library")
    i_runtime = prompt.index("# System Information")

    # Identity and persona definition are the stable cached head. The tool
    # catalog is turn-selected, so it belongs with the dynamic tail.
    assert i_definition < i_persona
    assert i_persona < i_boundary
    assert i_boundary < i_tools
    assert i_tools < i_memory
    assert i_tools < i_runtime


def test_cache_boundary_sits_after_persona_identity_before_dynamic() -> None:
    # P2a (#100): only the byte-stable persona DEFINITION (identity + baseline
    # voice) joins the cached head. The boundary sits after identity + persona
    # identity, and before the turn-selected tool catalog plus the per-turn
    # blocks (memory / runtime) that the provider bridge moves out to the
    # message tail.
    prompt = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))

    assert SYSTEM_PROMPT_CACHE_BOUNDARY in prompt
    i_boundary = prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert prompt.index("# Persona Runtime Plan") < i_boundary
    assert i_boundary < prompt.index("# Tool Use Guidance")
    assert i_boundary < prompt.index("# Memory Library")
    assert i_boundary < prompt.index("# System Information")


def test_selected_tool_changes_do_not_change_cacheable_head() -> None:
    prompt_a = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))
    prompt_b = PromptContextRenderer().render_system_prompt(_assembly_context(["beta_tool"]))

    head_a, tail_a = _split_prompt(prompt_a)
    head_b, tail_b = _split_prompt(prompt_b)

    assert head_a == head_b
    assert "alpha_tool" not in head_a
    assert "beta_tool" not in head_b
    assert "alpha_tool" not in tail_a
    assert "beta_tool" not in tail_b
    assert prompt_a == prompt_b


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

    prompt = PromptContextRenderer().render_system_prompt(context)

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

    prompt = PromptContextRenderer().render_system_prompt(context)

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

    prompt = PromptContextRenderer().render_system_prompt(context)

    assert "neutral" in prompt
    assert "medium" in prompt
    assert "score:" not in prompt
    assert "level:" not in prompt
    assert "0.03" not in prompt
    assert "0.55" not in prompt


def test_persona_identity_in_head_per_turn_steer_in_tail() -> None:
    # The persona DEFINITION (Identity Core + Baseline Voice) is stable across
    # turns and stays in the cached head. The per-turn STEER (register,
    # modulation, examples) is recomputed every turn by PersonaTurnPlanner, so it
    # must sit below the boundary or it invalidates the cached prefix each turn
    # (root cause of cache read=0 on the chat path).
    prompt = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))
    i_boundary = prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)

    # Stable persona definition — above the boundary (cached).
    assert prompt.index("## Identity Core") < i_boundary
    assert prompt.index("## Baseline Voice") < i_boundary

    # Per-turn steer — below the boundary (moved to the message tail).
    assert i_boundary < prompt.index("## Expression Policy")
    assert i_boundary < prompt.index("## Dynamic Modulation")
    assert i_boundary < prompt.index("## Relevant Persona Examples")


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
