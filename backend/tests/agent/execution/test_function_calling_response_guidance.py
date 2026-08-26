"""Prompt guidance owned by the function-calling response layer."""

from __future__ import annotations

from magi.agent.execution.function_calling.responses import FunctionCallingResponseMixin
from magi.utils.model_context_messages import is_working_context_message


class _Mixin(FunctionCallingResponseMixin):
    """Minimal concrete subclass to exercise prompt helpers."""


def test_tool_discovery_guidance_requires_focused_capability_queries() -> None:
    prompt = _Mixin()._build_execution_guidance()

    assert "Tool discovery rules:" in prompt
    assert "one focused capability gap" in prompt
    assert "domain/action/object" in prompt
    assert "concrete facts already known" in prompt
    assert "current_tools" in prompt
    assert "Do not pass the whole user request" in prompt


def test_final_response_guidance_is_typed_working_context() -> None:
    messages = [{"role": "user", "content": "Please finish the task."}]

    final_messages = _Mixin()._build_final_response_messages(messages)

    assert final_messages[:-1] == messages
    assert is_working_context_message(final_messages[-1])
    assert "Final Response Rules:" in str(final_messages[-1]["content"])
    assert "Tools are no longer available in this step." in str(
        final_messages[-1]["content"]
    )
