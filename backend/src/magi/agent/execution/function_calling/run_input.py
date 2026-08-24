"""Single front-door request for every unified agent run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from ...turn_input import UserTurnInput
from magi.control.run_control import RunControl

from ..completion_policy import CompletionPolicy
from ..checkpoint import AgentRunCheckpoint
from ..model_capabilities import ModelCapabilityProfile
from ..reasoning import ReasoningPolicy, ReasoningState

DEFAULT_MAX_ITERATIONS = 30


@dataclass(slots=True)
class AgentRunRequest:
    """A complete bounded run, independent of semantic route classification."""

    turn: UserTurnInput
    system_prompt: str
    selected_tools: list[str]
    user_id: str

    run_id: str = field(default_factory=lambda: uuid4().hex)
    parent_run_id: str | None = None
    checkpoint: AgentRunCheckpoint | None = None
    session_id: str | None = None
    session_run_id: str | None = None
    session_run_revision: int = 0
    turn_id: str | None = None
    conversation_history: list[dict[str, Any]] | None = None
    session_summary: str | None = None
    session_origin: str | None = None
    reply_context: Any | None = None
    ephemeral_context: str | None = None

    max_iterations: int = DEFAULT_MAX_ITERATIONS
    execution_preset: str = "chat"
    execution_agent_id: str = "chat_agent"
    execution_workspace: str | None = None
    llm_timeout_seconds: float | None = None
    final_response_json_mode: bool = False
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    reasoning_state: ReasoningState | None = None
    completion_policy: CompletionPolicy = field(default_factory=CompletionPolicy)
    context_sources: tuple[dict[str, Any], ...] = ()
    capability_resolution: dict[str, Any] = field(default_factory=dict)
    run_plan_provider: Callable[[], Any] | None = None
    model_capabilities: ModelCapabilityProfile | None = None

    control: RunControl | None = None

    def __post_init__(self) -> None:
        if self.checkpoint is None:
            return
        self.run_id = self.checkpoint.run_id
        self.reasoning_policy = self.checkpoint.reasoning_policy
        self.reasoning_state = self.checkpoint.reasoning_state

    @classmethod
    def headless(
        cls,
        *,
        turn: UserTurnInput,
        selected_tools: list[str],
        user_id: str,
        session_id: str | None = None,
        system_prompt: str = "",
        turn_id: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        execution_preset: str = "background",
        execution_agent_id: str = "chat_agent",
        execution_workspace: str | None = None,
        control: RunControl | None = None,
        reasoning_policy: ReasoningPolicy | None = None,
        reasoning_state: ReasoningState | None = None,
        llm_timeout_seconds: float | None = None,
        final_response_json_mode: bool = False,
        ephemeral_context: str | None = None,
        context_sources: tuple[dict[str, Any], ...] = (),
        checkpoint: AgentRunCheckpoint | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
    ) -> "AgentRunRequest":
        return cls(
            turn=turn,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            user_id=user_id,
            run_id=run_id or uuid4().hex,
            parent_run_id=parent_run_id,
            checkpoint=checkpoint,
            session_id=session_id,
            session_run_id=session_run_id,
            session_run_revision=session_run_revision,
            turn_id=turn_id,
            conversation_history=conversation_history,
            max_iterations=max_iterations,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
            control=control,
            reasoning_policy=reasoning_policy or ReasoningPolicy(),
            reasoning_state=reasoning_state,
            llm_timeout_seconds=llm_timeout_seconds,
            final_response_json_mode=final_response_json_mode,
            ephemeral_context=ephemeral_context,
            context_sources=context_sources,
        )


__all__ = ["AgentRunRequest", "DEFAULT_MAX_ITERATIONS"]
