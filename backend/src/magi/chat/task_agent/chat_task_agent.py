"""Runtime task agent for chat facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from magi.agent.cancel import SessionRunCancelToken
from magi.control.run_control import null_run_control
from magi.agent.trace import now_wall_ms
from magi.chat import ChatProjector, ChatReadService, ChatStore
from magi.config import get_config, get_user_preference
from magi.core.logger import get_logger
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import TaskAgent, TaskAgentRuntimeContext
from magi.agent.runtime.types import TaskAgentType
from magi.tools.registry import tool_registry
from magi.runtime_trace import RuntimeTraceStore
from magi.utils.runtime import get_runtime_paths
from magi.llm.streaming_events import stream_scope
from magi.agent.task_agents.handlers import (
    IntentDecision,
    ChatRuntimeContext,
    ExecutionRequest,
    ExecutionResult,
    ToolSelection,
)
from magi.chat.task_agent.postprocess_service import ChatPostProcessService
from magi.chat.task_agent.reply_context import ChatReplyContextMixin
from magi.chat.task_agent.recall_feedback_context import ChatRecallFeedbackContextMixin
from .rhythm import (
    is_conversation_rhythm_enabled,
)
from magi.chat.task_agent.session_control import ChatSessionControlMixin
from .streaming import (
    ChatStreamingMixin,
    format_llm_error as _format_llm_error,
)
from .runtime_dependencies import (
    ChatTaskAgentRuntimeCallbacks,
    ChatTaskAgentRuntimeConfig,
    build_chat_task_agent_runtime_parts,
)

logger = get_logger(__name__)

_RUNTIME_CONFIG_INIT_FIELDS = (
    "llm_adapter",
    "llm_pool",
    "memory",
    "unified_memory",
    "hybrid_retrieval_service",
    "history_cache_max_sessions",
    "history_fetch_limit",
    "skill_runner",
    "runtime_trace_store",
    "chat_store",
    "chat_projector",
    "chat_read_service_factory",
    "background_dispatcher",
    "background_launch_service",
    "permission_gateway_provider",
    "control_session_store_provider",
    "delivery_dispatcher_resolver",
    "conversation_log_resolver",
    "message_bus",
)


@dataclass(slots=True)
class _ChatRuntimePreferences:
    streaming_chat_enabled: bool
    allow_media_grounding_for_conversation: bool
    core_model_supports_vision: bool


@dataclass(slots=True)
class _ChatContextInputs:
    session_id: str
    active_persona_id: str | None
    history_context: Any
    history: list[dict[str, Any]]
    history_key: str
    recent_tool_errors: list[dict[str, Any]]
    recent_tool_state: list[dict[str, Any]]
    active_orchestrations: list[Any]
    reply_context: Any
    recall_feedback: Any
    preferences: _ChatRuntimePreferences


class ChatTaskAgent(
    ChatSessionControlMixin,
    ChatStreamingMixin,
    ChatReplyContextMixin,
    ChatRecallFeedbackContextMixin,
    TaskAgent[
        ChatRuntimeContext,
        IntentDecision,
        ToolSelection,
        ExecutionRequest,
        ExecutionResult,
    ],
):
    """Consumes chat facts and delegates execution to typed handlers."""

    def __init__(
        self,
        agent_id: str,
        llm_adapter=None,
        llm_pool=None,
        memory=None,
        unified_memory=None,
        hybrid_retrieval_service=None,
        memory_integration=None,
        history_cache_max_sessions: int = 500,
        history_fetch_limit: int = 1000,
        skill_runner=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        chat_store: ChatStore | None = None,
        chat_projector: ChatProjector | None = None,
        chat_read_service_factory: Callable[[], ChatReadService] | None = None,
        background_dispatcher: Any | None = None,
        background_launch_service: Any | None = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        control_session_store_provider: Callable[[], Any] | None = None,
        delivery_dispatcher_resolver: Callable[[], Any] | None = None,
        conversation_log_resolver: Callable[[], Any] | None = None,
        message_bus: Any | None = None,
    ) -> None:
        super().__init__(agent_type=TaskAgentType.CHAT, agent_id=agent_id)
        init_values = locals()
        self._store_runtime_roots(init_values)
        runtime_parts = build_chat_task_agent_runtime_parts(
            self._build_runtime_config(init_values),
            self._build_runtime_callbacks(),
        )
        self._install_runtime_parts(runtime_parts)
        self._bind_runtime_views()

    def _store_runtime_roots(self, init_values: dict[str, Any]) -> None:
        self.llm = init_values["llm_adapter"]
        self._llm_pool = init_values["llm_pool"]
        self.memory = init_values["memory"]
        self.unified_memory = init_values["unified_memory"]
        self.memory_integration = init_values["memory_integration"]
        self._chat_store = init_values["chat_store"]
        self._runtime_trace_store = init_values["runtime_trace_store"]

    def _build_runtime_config(self, init_values: dict[str, Any]) -> ChatTaskAgentRuntimeConfig:
        return ChatTaskAgentRuntimeConfig(
            agent_id=self.agent_id,
            runtime_key=self.runtime_key,
            **{field: init_values[field] for field in _RUNTIME_CONFIG_INIT_FIELDS},
        )

    def _build_runtime_callbacks(self) -> ChatTaskAgentRuntimeCallbacks:
        return ChatTaskAgentRuntimeCallbacks(
            get_event_emitter=lambda: self._event_emitter,
            get_task_agent_manager=lambda: self._task_agent_manager,
            get_sensor_hub=lambda: self._sensor_hub,
            max_fact_memory=self._max_fact_memory,
            drain_deferred_turns=self._drain_deferred_turns,
            deliver_final_response=self._deliver_final_response_from_postprocess,
            tool_advisory_provider=self._get_tool_advisory,
            session_workspace_provider=self._resolve_session_workspace_path,
            persist_turn_supersessions=self._persist_turn_supersessions_from_handler,
        )

    def _bind_runtime_views(self) -> None:
        self._last_batch_facts: list[FactRecord] = []

        # Keep this alias so existing read paths and tests see the same underlying store.
        self._conversation_history = self._context_assembler._conversation_history
        # Per-session recent-tool-call view; the chat agent (prompt assembly)
        # and postprocess (tool-event sink) both depend on this view
        # directly rather than going through ChatContextAssembler.
        self._tool_state_view = self._context_assembler.tool_state_view

    def _install_runtime_parts(self, runtime_parts: Any) -> None:
        self._chat_read_service_factory = runtime_parts.chat_read_service_factory
        self.context_decider = runtime_parts.context_decider
        self.prompt_context_assembler = runtime_parts.prompt_context_assembler
        self.prompt_context_renderer = runtime_parts.prompt_context_renderer
        self._chat_read_service = runtime_parts.chat_read_service
        self._attachment_resolver = runtime_parts.attachment_resolver
        self._context_retrieval_service = runtime_parts.context_retrieval_service
        self._context_service = runtime_parts.context_service
        self._context_assembler = runtime_parts.context_assembler
        self._fact_classifier = runtime_parts.fact_classifier
        self._prompt_service = runtime_parts.prompt_service
        self._interruption_classifier = runtime_parts.interruption_classifier
        self._session_run_coordinator = runtime_parts.session_run_coordinator
        self._planning_service = runtime_parts.planning_service
        self._orchestration_store = runtime_parts.orchestration_store
        self._task_orchestrator = runtime_parts.task_orchestrator
        self._transcript_summarizer = runtime_parts.transcript_summarizer
        self._postprocess_service = runtime_parts.postprocess_service
        self.function_calling_orchestrator = runtime_parts.function_calling_orchestrator
        self._handler_registry = runtime_parts.handler_registry
        self._coordinator = runtime_parts.coordinator

    @property
    def postprocess_service(self) -> ChatPostProcessService:
        """Expose the chat post-process service for external wiring."""
        return self._postprocess_service

    async def _deliver_final_response_from_postprocess(self, context, *, content):
        coordinator = getattr(self, "_coordinator", None)
        deliver = getattr(coordinator, "deliver_final_chat_response", None)
        if deliver is None:
            return []
        return await deliver(context, content=content)

    async def _persist_turn_supersessions_from_handler(
        self,
        superseded_turns: list[Any],
        updated_at_ms: int,
    ) -> None:
        """Bridge STEER supersessions from handler -> post-process service.

        Exposed as a callable on :class:`ChatHandlerDependencies` so the
        function-calling handler can emit STEER supersession bookkeeping
        whenever it drains persisted STEER pending turns into the inbox.
        """
        await self._postprocess_service.persist_turn_supersessions(
            superseded_turns=superseded_turns,
            updated_at_ms=updated_at_ms,
        )

    async def _resolve_session_workspace_path(self, *, user_id: str, session_id: str) -> str | None:
        summary = await self._chat_read_service.aget_session_summary(user_id, session_id)
        return summary.workspace_path if summary is not None else None

    async def _get_tool_advisory(
        self,
        task_context: str | None = None,
        tool_names: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Fetch notable L4 advisories for the coordinator."""
        available_tool_names = list(tool_names or tool_registry.list_tools())
        targeted_mode = bool(tool_names)
        advisories_by_tool = await self._collect_tool_advisories(
            available_tool_names=available_tool_names,
            task_context=task_context,
            targeted_mode=targeted_mode,
            tool_names=tool_names,
            limit=limit,
        )

        if targeted_mode:
            return _ordered_target_tool_advisories(advisories_by_tool, tool_names, limit)

        return _notable_tool_advisories(advisories_by_tool, limit)

    async def _collect_tool_advisories(
        self,
        *,
        available_tool_names: list[str],
        task_context: str | None,
        targeted_mode: bool,
        tool_names: list[str] | None,
        limit: int,
    ) -> dict[str, dict]:
        advisories_by_tool = _advisories_by_tool(
            await self._fetch_l4_tool_advisories(
                task_context=task_context,
                targeted_mode=targeted_mode,
                tool_names=tool_names,
                limit=limit,
            )
        )
        _merge_trace_tool_stats(
            advisories_by_tool,
            await self._fetch_tool_trace_stats(available_tool_names),
        )
        return advisories_by_tool

    async def _fetch_tool_trace_stats(
        self,
        available_tool_names: list[str],
    ) -> dict[str, dict[str, float | int]]:
        if self._runtime_trace_store is None:
            return {}
        try:
            return await self._runtime_trace_store.get_tool_execution_stats(available_tool_names)
        except Exception as exc:
            logger.debug("Failed to fetch runtime trace tool stats: %s", exc)
            return {}

    async def _fetch_l4_tool_advisories(
        self,
        *,
        task_context: str | None,
        targeted_mode: bool,
        tool_names: list[str] | None,
        limit: int,
    ) -> list[dict]:
        if self.unified_memory is None or self.unified_memory.l4 is None:
            return []
        try:
            if targeted_mode:
                return await self.unified_memory.l4.get_tool_advisory(
                    tool_names=list(tool_names or []),
                    task_context=task_context,
                )
            return await self.unified_memory.l4.get_notable_advisories(
                task_context=task_context,
                limit=limit,
            )
        except Exception as exc:
            logger.debug("Failed to fetch L4 tool advisories: %s", exc)
            return []

    async def add_fact(self, fact: FactRecord) -> bool:
        """Enqueue the fact, fast-pathing obvious INTERRUPT user turns.

        When a USER_MESSAGE arrives while an earlier run is still executing
        and the text matches the INTERRUPT rule patterns, we proactively
        call ``request_cancel`` on the coordinator so the in-flight
        execution can bail out at the next ``cancel_token`` probe — even
        before the run loop gets a chance to pull the fact off the queue
        and classify it.
        """
        await self._request_ingress_interrupt(fact)
        return await super().add_fact(fact)

    async def handle_fact(self, fact: FactRecord) -> None:
        _ = fact

    async def merge_facts(self, new_facts: list[FactRecord]) -> list[FactRecord]:
        self._last_batch_facts = list(new_facts)
        return await super().merge_facts(new_facts)

    async def build_context(self, merged_facts: list[FactRecord]) -> ChatRuntimeContext:
        base_context = await super().build_context(merged_facts)
        batch_facts = list(self._last_batch_facts)
        latest_fact = _latest_runtime_fact(base_context)
        classified = self._fact_classifier.classify(
            agent_id=self.agent_id,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
        )
        run_decision = await self._session_run_coordinator.aroute(classified)
        await self._persist_context_supersessions(run_decision, latest_fact)

        context_inputs = await self._load_context_inputs(classified, run_decision)
        turn_control = null_run_control()
        if run_decision.active_run is not None:
            turn_control.cancel_token = SessionRunCancelToken(
                coordinator=self._session_run_coordinator,
                session_id=context_inputs.session_id,
                run_id=run_decision.active_run.run_id,
                revision=int(run_decision.active_run.revision or 0),
            )
        self._register_turn_control(context_inputs.session_id, run_decision, turn_control)

        return self._build_chat_runtime_context(
            base_context=base_context,
            latest_fact=latest_fact,
            batch_facts=batch_facts,
            classified=classified,
            run_decision=run_decision,
            context_inputs=context_inputs,
            turn_control=turn_control,
        )

    async def _load_context_inputs(self, classified: Any, run_decision: Any) -> _ChatContextInputs:
        session_id = self._context_assembler.require_session_id(
            classified.user_id, classified.session_id
        )
        active_persona_id = await self._resolve_context_persona_id(run_decision.latest_payload)
        history_context = await self._context_assembler.get_or_load_history_context(
            classified.user_id,
            session_id,
            active_persona_id=active_persona_id,
        )
        history_key = self._context_assembler.history_key(classified.user_id, session_id)
        active_orchestrations = await self._orchestration_store.list_orchestrations(
            user_id=classified.user_id,
            session_id=session_id,
            statuses=["running", "aggregating"],
        )
        reply_context = await self._resolve_reply_context(run_decision.latest_payload)
        recall_feedback = await self._resolve_recall_feedback_context(run_decision.latest_payload)
        return _ChatContextInputs(
            session_id=session_id,
            active_persona_id=active_persona_id,
            history_context=history_context,
            history=history_context.messages,
            history_key=history_key,
            recent_tool_errors=self._tool_state_view.recent_errors(history_key),
            recent_tool_state=self._tool_state_view.recent_state(history_key),
            active_orchestrations=active_orchestrations,
            reply_context=reply_context,
            recall_feedback=recall_feedback,
            preferences=_resolve_chat_runtime_preferences(),
        )

    def _build_chat_runtime_context(
        self,
        *,
        base_context: TaskAgentRuntimeContext,
        latest_fact: FactRecord | None,
        batch_facts: list[FactRecord],
        classified: Any,
        run_decision: Any,
        context_inputs: _ChatContextInputs,
        turn_control: Any,
    ) -> ChatRuntimeContext:
        return ChatRuntimeContext(
            latest_fact=latest_fact if isinstance(latest_fact, FactRecord) else None,
            recent_facts=_recent_runtime_facts(base_context),
            batch_facts=batch_facts,
            agent_id=self.agent_id,
            agent_type=_runtime_agent_type(base_context),
            runtime_key=_runtime_key(base_context, self.runtime_key),
            user_id=classified.user_id,
            session_id=context_inputs.session_id,
            history_key=context_inputs.history_key,
            history=context_inputs.history,
            conversation_history=context_inputs.history,
            active_orchestrations=[item.to_dict() for item in context_inputs.active_orchestrations],
            recent_tool_errors=context_inputs.recent_tool_errors,
            recent_tool_state=context_inputs.recent_tool_state,
            latest_user_message=run_decision.planner_user_message,
            incoming_fact_kind=run_decision.planner_fact_kind,
            latest_payload=run_decision.latest_payload,
            active_run=run_decision.active_run,
            session_run_id=(
                run_decision.active_run.run_id if run_decision.active_run is not None else None
            ),
            session_run_revision=(
                run_decision.active_run.revision if run_decision.active_run is not None else 0
            ),
            session_run_disposition=run_decision.run_disposition,
            planner_fact=run_decision.planner_fact,
            planner_fact_kind=run_decision.planner_fact_kind,
            planner_payload=run_decision.latest_payload,
            pending_turns=list(run_decision.checkpoint_pending_turns),
            reply_context=context_inputs.reply_context,
            recall_feedback=context_inputs.recall_feedback,
            session_summary=context_inputs.history_context.session_summary,
            session_origin=context_inputs.history_context.session_origin,
            active_persona_id=context_inputs.active_persona_id,
            streaming_chat_enabled=context_inputs.preferences.streaming_chat_enabled,
            allow_media_grounding_for_conversation=(
                context_inputs.preferences.allow_media_grounding_for_conversation
            ),
            core_model_supports_vision=context_inputs.preferences.core_model_supports_vision,
            control=turn_control,
        )

    async def _persist_context_supersessions(
        self,
        run_decision: Any,
        latest_fact: FactRecord | None,
    ) -> None:
        if not run_decision.superseded_turns:
            return
        updated_at_ms = (
            int(latest_fact.timestamp * 1000)
            if isinstance(latest_fact, FactRecord)
            else now_wall_ms()
        )
        await self._postprocess_service.persist_turn_supersessions(
            superseded_turns=run_decision.superseded_turns,
            updated_at_ms=updated_at_ms,
        )

    def _register_turn_control(
        self,
        session_id: str,
        run_decision: Any,
        turn_control: Any,
    ) -> None:
        if run_decision.active_run is None:
            return
        self._session_run_coordinator.register_active_run_control(
            session_id,
            run_decision.active_run.run_id,
            turn_control,
        )

    async def _resolve_context_persona_id(self, latest_payload: object) -> str | None:
        turn_id = str(getattr(latest_payload, "turn_id", "") or "").strip()
        if self._chat_store is not None and turn_id:
            try:
                user_message = await self._chat_store.get_latest_message_for_turn(
                    turn_id,
                    message_kind="user_text",
                )
                if user_message is not None and user_message.persona_id:
                    return str(user_message.persona_id).strip() or None
            except Exception:
                logger.debug("Failed to resolve persona id from user turn", turn_id=turn_id)
        try:
            from magi.personality.persona_repository import PersonaRepository

            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            active_id = await repo.get_active_id()
        except Exception:
            return None
        return str(active_id or "").strip() or None

    async def match_intent(self, context: ChatRuntimeContext):
        return await self._coordinator.match_intent(context)

    async def match_tools(self, context: ChatRuntimeContext, intent_result):
        return await self._coordinator.match_tools(context, intent_result)

    async def assemble_llm_params(
        self,
        context: ChatRuntimeContext,
        intent_result,
        tool_result,
    ) -> ExecutionRequest:
        return await self._coordinator.assemble_request(context, intent_result, tool_result)

    async def call_llm(
        self, context: ChatRuntimeContext, llm_params: ExecutionRequest
    ) -> ExecutionResult:
        sink = None
        turn_id = str(getattr(context.latest_payload, "turn_id", "") or "").strip() or None
        if (
            context.user_id
            and context.session_id
            and turn_id
            and self._streaming_enabled(context.user_id)
        ):
            sink = self._build_stream_sink(
                user_id=context.user_id,
                session_id=context.session_id,
                turn_id=turn_id,
                persona_id=context.active_persona_id,
            )
        try:
            async with stream_scope(sink, source="chat"):
                return await self._coordinator.execute(llm_params)
        except Exception as exc:
            logger.error(
                "ChatTaskAgent LLM execution failed",
                session_id=context.session_id,
                turn_id=turn_id,
                error=str(exc),
                exc_info=True,
            )
            if sink is not None:
                await self._emit_llm_error(context, exc)
            correlation_id = (
                str(context.latest_fact.correlation_id or "").strip()
                if isinstance(context.latest_fact, FactRecord)
                else None
            )
            return ExecutionResult(
                mode=llm_params.mode,
                response_text=_format_llm_error(exc),
                root_user_message=context.latest_user_message,
                correlation_id=correlation_id,
                message_started_at=getattr(llm_params, "message_started_at", None),
                turn_id=turn_id,
                streamed=sink is not None,
            )

    def _streaming_enabled(self, _user_id: str) -> bool:
        try:
            return (
                bool(get_user_preference("streaming_chat_enabled", False))
                and not is_conversation_rhythm_enabled()
            )
        except Exception:
            return False

    async def parse_result(self, context: ChatRuntimeContext, raw_result: ExecutionResult) -> None:
        try:
            await self._postprocess_service.handle(context, raw_result)
        finally:
            # Unregister the turn's RunControl now that the turn is done.
            # The bundle's signals (asyncio.Event etc.) are not persistable
            # so keeping a dead reference accomplishes nothing.
            if context.session_id and context.session_run_id:
                self._session_run_coordinator.unregister_active_run_control(
                    context.session_id, context.session_run_id
                )

    def get_conversation_history(self, user_id: str, session_id: str) -> list[dict]:
        return self._context_assembler.get_conversation_history(user_id, session_id)

    def clear_conversation_history(self, user_id: str, session_id: str) -> None:
        self._context_assembler.clear_conversation_history(user_id, session_id)

    def get_llm_max_tokens(self) -> int:
        try:
            return int(get_config().llm.max_tokens)
        except Exception:
            return 4096


def _latest_runtime_fact(base_context: Any) -> FactRecord | None:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return None
    latest_fact = base_context.latest_fact
    return latest_fact if isinstance(latest_fact, FactRecord) else None


def _recent_runtime_facts(base_context: Any) -> list[FactRecord]:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return []
    return list(base_context.recent_facts)


def _runtime_agent_type(base_context: Any) -> str:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return TaskAgentType.CHAT.value
    return str(base_context.agent_type)


def _runtime_key(base_context: Any, fallback: str) -> str:
    if not isinstance(base_context, TaskAgentRuntimeContext):
        return fallback
    return str(base_context.runtime_key)


def _advisories_by_tool(base_advisories: list[dict]) -> dict[str, dict]:
    advisories_by_tool: dict[str, dict] = {}
    for advisory in base_advisories:
        tool_name = str(advisory.get("tool_name") or "").strip()
        if tool_name:
            advisories_by_tool[tool_name] = dict(advisory)
    return advisories_by_tool


def _merge_trace_tool_stats(
    advisories_by_tool: dict[str, dict],
    trace_stats: dict[str, dict[str, float | int]],
) -> None:
    for tool_name, stats in trace_stats.items():
        total_calls = int(stats.get("total_calls") or 0)
        if total_calls <= 0:
            continue
        _merge_one_trace_tool_stat(advisories_by_tool, tool_name, stats, total_calls)


def _merge_one_trace_tool_stat(
    advisories_by_tool: dict[str, dict],
    tool_name: str,
    stats: dict[str, float | int],
    total_calls: int,
) -> None:
    success_rate = float(stats.get("success_rate") or 0.0)
    advisory = advisories_by_tool.setdefault(
        tool_name,
        {
            "tool_name": tool_name,
            "available": True,
            "breaker_state": "closed",
            "strategy_hint": None,
            "context_fit": 0.0,
        },
    )
    advisory["success_rate"] = success_rate
    advisory["total_attempts"] = total_calls
    advisory["failure_count"] = int(stats.get("failed_calls") or 0)
    advisory["stats_source"] = "runtime_trace.trace_tools"
    if success_rate < 0.7 and total_calls >= 3:
        advisory["risk_note"] = f"Low success rate ({success_rate:.0%} over {total_calls} attempts)"


def _ordered_target_tool_advisories(
    advisories_by_tool: dict[str, dict],
    tool_names: list[str] | None,
    limit: int,
) -> list[dict]:
    ordered: list[dict] = []
    for tool_name in list(tool_names or []):
        advisory = advisories_by_tool.get(tool_name)
        if advisory is not None:
            ordered.append(advisory)
    return ordered[:limit]


def _notable_tool_advisories(advisories_by_tool: dict[str, dict], limit: int) -> list[dict]:
    return [
        advisory
        for advisory in advisories_by_tool.values()
        if advisory.get("strategy_hint") is not None
        or advisory.get("breaker_state") != "closed"
        or (
            float(advisory.get("success_rate") or 0.0) < 0.7
            and int(advisory.get("total_attempts") or 0) >= 3
        )
    ][:limit]


def _resolve_chat_runtime_preferences() -> _ChatRuntimePreferences:
    streaming_chat_enabled = bool(get_user_preference("streaming_chat_enabled", False))
    if is_conversation_rhythm_enabled():
        streaming_chat_enabled = False
    core_selection = get_config().llm.selections.get("core")
    core_model_supports_vision = bool(
        getattr(getattr(core_selection, "capabilities", None), "vision", False)
    )
    return _ChatRuntimePreferences(
        streaming_chat_enabled=streaming_chat_enabled,
        allow_media_grounding_for_conversation=bool(
            get_user_preference("allow_media_grounding_for_conversation", False)
        ),
        core_model_supports_vision=core_model_supports_vision,
    )
