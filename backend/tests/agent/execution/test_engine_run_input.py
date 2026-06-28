"""ADR-0004 P4-1a: the EngineRunInput front-door is faithful to the engine.

EngineRunInput is a parameter object that mirrors
``FunctionCallingOrchestrator.execute_with_tools`` 1:1, and ``orchestrator.run``
forwards it verbatim. These tests lock that contract so the two can never drift
(a new engine kwarg without a matching field, or a changed default, fails here).
"""
from __future__ import annotations

import inspect
from dataclasses import MISSING, fields

import pytest

from magi.agent.execution.function_calling.orchestrator import FunctionCallingOrchestrator
from magi.agent.execution.function_calling.run_input import EngineRunInput
from magi.agent.turn_input import UserTurnInput


def _turn() -> UserTurnInput:
    return UserTurnInput(text="hi", attachments=[], user_id="u", session_id="s")


def _engine_params() -> dict[str, inspect.Parameter]:
    sig = inspect.signature(FunctionCallingOrchestrator.execute_with_tools)
    return {name: p for name, p in sig.parameters.items() if name != "self"}


def test_field_names_match_execute_with_tools_params() -> None:
    field_names = {f.name for f in fields(EngineRunInput)}
    assert field_names == set(_engine_params())


def test_field_defaults_match_execute_with_tools_defaults() -> None:
    field_map = {f.name: f for f in fields(EngineRunInput)}
    for name, param in _engine_params().items():
        if param.default is inspect.Parameter.empty:
            # required engine arg → field must also be required (no default).
            f = field_map[name]
            assert f.default is MISSING and f.default_factory is MISSING, name
            continue
        f = field_map[name]
        default = f.default if f.default is not MISSING else f.default_factory()
        assert default == param.default, f"{name}: {default!r} != {param.default!r}"


@pytest.mark.asyncio
async def test_run_forwards_every_field_verbatim() -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.kwargs: dict | None = None

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            self.kwargs = kwargs
            return "outcome-sentinel"

    rec = _Recorder()
    run_input = EngineRunInput(
        turn=_turn(),
        system_prompt="sys",
        selected_tools=["t"],
        user_id="u",
        session_id="s",
        intent="background",
        execution_agent_id="bg:1",
        max_iterations=7,
    )

    # Call the unbound method with our recorder as `self` — run() is a pure
    # adapter, so it needs nothing else off the orchestrator.
    out = await FunctionCallingOrchestrator.run(rec, run_input)

    assert out == "outcome-sentinel"
    assert rec.kwargs is not None
    # Exactly the engine's params, no more, no less.
    assert set(rec.kwargs) == set(_engine_params())
    # Each forwarded value is the input's field value, by identity/equality.
    for f in fields(EngineRunInput):
        assert rec.kwargs[f.name] == getattr(run_input, f.name)


def test_headless_leaves_chat_fields_inert() -> None:
    run_input = EngineRunInput.headless(
        turn=_turn(),
        selected_tools=["web-search"],
        user_id="u",
        session_id="s",
        execution_agent_id="background:bg_1",
        intent="background",
        max_iterations=5,
    )
    # Chat-only session/control fields are unreachable via headless() and stay
    # at their inert defaults.
    assert run_input.session_run_id is None
    assert run_input.session_run_revision == 0
    assert run_input.session_summary is None
    assert run_input.session_origin is None
    assert run_input.reply_context is None
    assert run_input.control is None
    assert run_input.steer_inbox is None
    assert run_input.detach_signal is None
    assert run_input.route_decision is None
    # Headless knobs applied / defaulted.
    assert run_input.system_prompt == ""
    assert run_input.disable_thinking is True
    assert run_input.intent == "background"
    assert run_input.execution_agent_id == "background:bg_1"


def test_headless_default_execution_agent_id_matches_engine_default() -> None:
    # The skill subagent relies on the engine's default execution_agent_id
    # ("chat_agent") by not passing one; headless() must preserve that so the
    # migration is behavior-faithful.
    engine_default = _engine_params()["execution_agent_id"].default
    run_input = EngineRunInput.headless(
        turn=_turn(), selected_tools=[], user_id="u", session_id="s"
    )
    assert run_input.execution_agent_id == engine_default
