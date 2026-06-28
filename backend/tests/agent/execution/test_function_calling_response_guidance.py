"""Prompt guidance owned by the function-calling response layer."""

from __future__ import annotations

from magi.agent.execution.function_calling.responses import FunctionCallingResponseMixin


class _Mixin(FunctionCallingResponseMixin):
    """Minimal concrete subclass to exercise prompt helpers."""


def test_tool_discovery_guidance_requires_focused_capability_queries() -> None:
    prompt = _Mixin()._augment_system_prompt("# System\nBe useful.")

    assert "Tool discovery rules:" in prompt
    assert "one focused capability gap" in prompt
    assert "domain/action/object" in prompt
    assert "concrete facts already known" in prompt
    assert "current_tools" in prompt
    assert "Do not pass the whole user request" in prompt


def test_final_response_prompt_preserves_segmentation_protocol() -> None:
    system_prompt = (
        "# System\n"
        "Be useful.\n"
        "# Reply Segmentation Protocol\n"
        "[System Notice: Use ‖ only when appropriate.]\n"
        "# Tool Use Guidance\n"
        "Use tools when needed.\n"
        "Tool recovery rules:\n"
        "- use tools\n"
    )

    final_prompt = _Mixin()._build_final_response_system_prompt(system_prompt)

    assert "# Reply Segmentation Protocol" in final_prompt
    assert "Use ‖ only when appropriate" in final_prompt
    assert "# Tool Use Guidance" not in final_prompt
    assert "Tool recovery rules" not in final_prompt
