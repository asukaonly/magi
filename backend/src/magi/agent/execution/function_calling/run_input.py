"""Engine front-door input (ADR-0004 P4-1a).

``EngineRunInput`` is the single, typed parameter object for one bounded
LLM↔tool run on the Run Engine. It mirrors ``FunctionCallingOrchestrator.
execute_with_tools`` 1:1 (a parameter object), so a caller builds *one* value
and hands it to :meth:`FunctionCallingOrchestrator.run` instead of hand-wiring
~27 keyword arguments at every surface.

This is the load-bearing seam ADR-0004 calls out: a future driver registry's
``RunDriver`` builds an ``EngineRunInput`` (from a trigger + domain data) and the
engine runs it — the engine knows nothing about chat / background / worker /
subagent.

The field set and defaults are kept *byte-faithful* to ``execute_with_tools``;
``tests/agent/execution/test_engine_run_input.py`` asserts parity via
``inspect.signature`` so the two can never silently drift.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ....config.models import ThinkingDepth
from ...cancel import CancelToken
from magi.control.run_control import DetachSignal, RunControl, SteerInbox
from ...turn_input import UserTurnInput

if TYPE_CHECKING:
    from ....tools.context_routing.route_decision import RouteDecision

# Mirror of FunctionCallingOrchestrator.MAX_ITERATIONS (the execute_with_tools
# default). Duplicated here to avoid a run_input → orchestrator import cycle;
# the parity test guards against drift.
DEFAULT_MAX_ITERATIONS = 30


@dataclass(slots=True)
class EngineRunInput:
    """A complete, typed description of one Run Engine invocation.

    Fields and defaults mirror ``execute_with_tools`` exactly. Surfaces that run
    headless (no chat session / control plane) should prefer :meth:`headless`,
    which exposes only the relevant knobs and leaves the chat-only fields
    (``session_run_id``, ``control``, ``steer_inbox``, ``detach_signal``,
    ``route_decision`` …) at their inert defaults.
    """

    # --- required core (no execute_with_tools default) ---
    turn: UserTurnInput
    system_prompt: str
    selected_tools: List[str]
    user_id: str

    # --- session / checkpoint (chat-rich) ---
    session_id: Optional[str] = None
    session_run_id: str | None = None
    session_run_revision: int = 0
    turn_id: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    session_summary: str | None = None
    session_origin: str | None = None
    reply_context: Any | None = None
    ephemeral_context: str | None = None

    # --- engine knobs ---
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    disable_thinking: bool = True
    intent: str = "unknown"
    execution_agent_id: str = "chat_agent"
    execution_workspace: Optional[str] = None
    llm_timeout_seconds: Optional[float] = None
    final_response_json_mode: bool = False
    thinking_depth: ThinkingDepth | None = None

    # --- control plane (chat-rich) ---
    cancel_token: CancelToken | None = None
    steer_inbox: SteerInbox | None = None
    detach_signal: DetachSignal | None = None
    control: RunControl | None = None
    route_decision: "RouteDecision | None" = None

    @classmethod
    def headless(
        cls,
        *,
        turn: UserTurnInput,
        selected_tools: List[str],
        user_id: str,
        session_id: str | None = None,
        system_prompt: str = "",
        turn_id: str | None = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        intent: str = "background",
        execution_agent_id: str = "chat_agent",
        execution_workspace: str | None = None,
        cancel_token: CancelToken | None = None,
        thinking_depth: ThinkingDepth | None = None,
        disable_thinking: bool = True,
        llm_timeout_seconds: float | None = None,
        final_response_json_mode: bool = False,
        ephemeral_context: str | None = None,
    ) -> "EngineRunInput":
        """Build an input for a headless run (background / worker / subagent).

        Deliberately exposes *only* the knobs a headless surface needs; the
        chat-only session/control fields are unreachable here and stay at their
        inert defaults, so a headless caller cannot accidentally smuggle in a
        session_run checkpoint or a steer/detach signal.
        """
        return cls(
            turn=turn,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            conversation_history=conversation_history,
            max_iterations=max_iterations,
            intent=intent,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
            cancel_token=cancel_token,
            thinking_depth=thinking_depth,
            disable_thinking=disable_thinking,
            llm_timeout_seconds=llm_timeout_seconds,
            final_response_json_mode=final_response_json_mode,
            ephemeral_context=ephemeral_context,
        )

    def to_execute_kwargs(self) -> Dict[str, Any]:
        """Project this input into the exact ``execute_with_tools`` kwargs.

        A shallow field→value mapping (no recursion into ``turn`` / ``control``
        / etc.). This is the canonical unpack used by
        :meth:`FunctionCallingOrchestrator.run`; engine test doubles reuse it so
        their ``run`` stays a faithful one-liner over their own
        ``execute_with_tools``.
        """
        return {f.name: getattr(self, f.name) for f in fields(self)}


__all__ = ["EngineRunInput", "DEFAULT_MAX_ITERATIONS"]
