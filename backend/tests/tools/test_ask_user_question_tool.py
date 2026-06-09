"""Unit tests for the thin ``ask_user_question`` tool.

Post Phase 4 Task 1 the tool delegates the control-protocol orchestration to
``ctx.capabilities.interaction.ask(...)`` (the SDK ``InteractionPort``) and only
owns request validation + mapping the returned :class:`AskOutcome` onto a
:class:`ToolResult`. These tests inject a fake ``InteractionPort`` and assert
that mapping; the full control-flow parity is pinned by
``tests/tools/test_ask_user_question_parity.py``.
"""

from typing import Any

import pytest

from magi.agent.cancel import EventCancelToken
from magi.tools.builtin.ask_user_question_tool import AskUserQuestionTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext
from magi_plugin_sdk.capabilities import AskOutcome, ToolCapabilities


class _FakeInteraction:
    """Records the ask call and returns a preset outcome (or raises)."""

    def __init__(self, outcome: AskOutcome | None = None, *, raises: Exception | None = None) -> None:
        self._outcome = outcome
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> AskOutcome:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        assert self._outcome is not None
        return self._outcome


def _ctx(interaction: Any, **overrides: Any) -> ToolExecutionContext:
    env = {"session_id": "session-1", "turn_id": "turn-1"}
    env.update(overrides.pop("env_vars", {}))
    kwargs: dict[str, Any] = dict(
        agent_id="chat",
        env_vars=env,
        permissions=[],
        enabled_features=[],
        capabilities=ToolCapabilities(interaction=interaction),
    )
    kwargs.update(overrides)
    return ToolExecutionContext(**kwargs)


@pytest.mark.asyncio
async def test_maps_answered_outcome_to_success() -> None:
    interaction = _FakeInteraction(
        AskOutcome(answered=True, answer="blue", resolution="user", timed_out=False)
    )
    result = await AskUserQuestionTool().execute(
        {"question": "Favourite colour?", "options": ["red", "blue"], "timeout_seconds": 30},
        _ctx(interaction),
    )
    assert result.success is True
    assert result.data == {"answer": "blue"}
    # The tool forwards the parsed request to the port.
    assert interaction.calls[0]["question"] == "Favourite colour?"
    assert interaction.calls[0]["options"] == ["red", "blue"]
    assert interaction.calls[0]["timeout_seconds"] == 30.0
    assert interaction.calls[0]["background"] is False


@pytest.mark.asyncio
async def test_maps_timeout_outcome_to_failure() -> None:
    interaction = _FakeInteraction(
        AskOutcome(answered=False, answer=None, resolution="timeout", timed_out=True)
    )
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "timeout_seconds": 5},
        _ctx(interaction),
    )
    assert result.success is False
    assert "no answer within 5s" in (result.error or "")


@pytest.mark.asyncio
async def test_maps_cancelled_outcome_to_cancelled() -> None:
    interaction = _FakeInteraction(
        AskOutcome(answered=False, answer=None, resolution="cancelled", timed_out=False)
    )
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "timeout_seconds": 30},
        _ctx(interaction),
    )
    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert result.error == "run cancelled before answer"


@pytest.mark.asyncio
async def test_early_cancellation_short_circuits_before_port() -> None:
    """A run cancelled before the tool starts must not reach the port."""
    interaction = _FakeInteraction(
        AskOutcome(answered=True, answer="x", resolution="user", timed_out=False)
    )
    token = EventCancelToken()
    token.cancel("test_cancel")
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?", "timeout_seconds": 30},
        _ctx(interaction, cancellation=token),
    )
    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert interaction.calls == []


@pytest.mark.asyncio
async def test_missing_interaction_capability_fails() -> None:
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?"},
        ToolExecutionContext(
            agent_id="chat",
            env_vars={"session_id": "session-1"},
            permissions=[],
            enabled_features=[],
            capabilities=ToolCapabilities(),
        ),
    )
    assert result.success is False
    assert "interaction capability" in (result.error or "")


@pytest.mark.asyncio
async def test_runtime_error_from_port_maps_to_failure() -> None:
    interaction = _FakeInteraction(raises=RuntimeError("control_session_store binding is not initialized"))
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?"},
        _ctx(interaction),
    )
    assert result.success is False
    assert "not initialized" in (result.error or "")


@pytest.mark.asyncio
async def test_background_without_optin_refused_before_port() -> None:
    interaction = _FakeInteraction(
        AskOutcome(answered=True, answer="x", resolution="user", timed_out=False)
    )
    result = await AskUserQuestionTool().execute(
        {"question": "Proceed?"},
        _ctx(interaction, agent_id="background:bg_1", env_vars={"intent": "background_scheduler"}),
    )
    assert result.success is False
    assert "background" in (result.error or "").lower()
    assert interaction.calls == []


def test_tool_registry_resolves_ask_alias() -> None:
    registry = ToolRegistry()
    registry.register(AskUserQuestionTool)

    assert isinstance(registry.get_tool("ask"), AskUserQuestionTool)
    assert registry.get_tool_info("ask") is not None
