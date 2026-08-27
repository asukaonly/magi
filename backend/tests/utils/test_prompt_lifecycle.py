"""Stable prompt-boundary contracts for unified agent requests."""

from __future__ import annotations

import pytest

from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.turn_input import UserTurnInput
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.context.prompt_lifecycle import DEFAULT_HEADLESS_SYSTEM_PROMPT


def test_headless_request_uses_canonical_stable_prompt_by_default() -> None:
    request = AgentRunRequest.headless(
        turn=UserTurnInput(text="run the task"),
        selected_tools=[],
        user_id="user-1",
    )

    assert request.system_prompt == DEFAULT_HEADLESS_SYSTEM_PROMPT
    assert request.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)


@pytest.mark.parametrize(
    "system_prompt",
    [
        "missing boundary",
        f"stable\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\ndynamic tail",
        f"{SYSTEM_PROMPT_CACHE_BOUNDARY}\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
    ],
)
def test_agent_run_request_rejects_non_stable_system_prompt(
    system_prompt: str,
) -> None:
    with pytest.raises(ValueError, match="Stable system prompt"):
        AgentRunRequest(
            turn=UserTurnInput(text="run the task"),
            system_prompt=system_prompt,
            selected_tools=[],
            user_id="user-1",
        )
