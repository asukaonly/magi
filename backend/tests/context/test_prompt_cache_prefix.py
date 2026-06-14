"""Prompt-cache prefix-stability tests (issue #97).

Prompt caching on every provider is a prefix match: any byte that changes
between consecutive requests invalidates the cache from that point onward.
These tests pin the two prefix-stabilising guarantees for the system prompt:

1. Static blocks (identity + tool catalog) render BEFORE the per-turn
   dynamic blocks (persona plan, memory, runtime/time) so the largest stable
   chunk sits at the front of the prefix.
2. The tool list — both the wire ``tools`` parameter and the in-prompt tool
   catalog — serialises in a deterministic, name-sorted order, so an unchanged
   tool SET produces byte-identical output even when the upstream selector
   reranks it per turn.
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
                register="task",
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


def test_static_blocks_render_before_dynamic_blocks() -> None:
    prompt = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))

    i_definition = prompt.index("# System Definition")
    i_tools = prompt.index("# Tool Information")
    i_persona = prompt.index("# Persona Runtime Plan")
    i_memory = prompt.index("# Memory Library")
    i_runtime = prompt.index("# System Information")

    # Identity stays first; the tool catalog (static when the tool set is
    # stable) must precede every per-turn dynamic block.
    assert i_definition < i_tools
    assert i_tools < i_persona
    assert i_tools < i_memory
    assert i_tools < i_runtime


def test_cache_boundary_sits_after_persona_before_dynamic() -> None:
    # P2a (#100): persona joins the stable head, so the boundary now sits after
    # identity + tool catalog + persona, and before the per-turn blocks (memory /
    # runtime) that the provider bridge moves out to the message tail.
    prompt = PromptContextRenderer().render_system_prompt(_assembly_context(["alpha_tool"]))

    assert SYSTEM_PROMPT_CACHE_BOUNDARY in prompt
    i_boundary = prompt.index(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert prompt.index("# Tool Information") < i_boundary
    assert prompt.index("# Persona Runtime Plan") < i_boundary
    assert i_boundary < prompt.index("# Memory Library")
    assert i_boundary < prompt.index("# System Information")


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


def test_tool_catalog_text_order_is_name_stable() -> None:
    renderer = PromptContextRenderer()
    catalog = ToolCatalogContext(
        selected_tools=["zebra", "alpha"],
        tool_descriptions=[
            {"name": "zebra", "description": "z", "type": "tool"},
            {"name": "alpha", "description": "a", "type": "tool"},
        ],
    )

    text = "\n".join(renderer._render_tool_catalog(catalog))

    # Both the "Selected Tools" list and the "Tool Catalog" list are sorted.
    assert text.index("* alpha") < text.index("* zebra")
    assert text.index("**alpha**") < text.index("**zebra**")
