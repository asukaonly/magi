"""Memory query tool for retrieving memories across the rewritten L0-L4 layers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...plugins.provider import resolve_plugin_projection_service
from ..schema import (
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
    ParameterType,
)

_QUERY_MODE_DESCRIPTION = (
    "The retrieval mode that best matches the user's intent. Pick exactly one. "
    "Examples:\n"
    '  - exact_fact: "What\'s my default editor?" / "我喜欢什么音乐" / "我爸的电话".\n'
    '  - current_state: "What am I working on right now?" / "我现在的项目是什么".\n'
    '  - episode_recall: "What did I do at 3pm yesterday?" / "上周二的会议讨论了什么".\n'
    '  - experience_recall: "Tell me about that Japan trip" / "回忆一下那次日本旅行".\n'
    '  - cross_session: "How many times did I talk about X?" / "列出所有讨论过 X 的会话".\n'
    '  - temporal_compare: "How has my code style changed?" / "和上个月相比我看的网站有什么变化".\n'
    '  - summary: "Recap what I did last week" / "总结一下我上周" (broad period recap, multiple kinds of activity).\n'
    '  - activity_summary: "What did I browse yesterday?" / "我最近在 Chrome 上看什么" / "我这周听了什么音乐" '
    "(one specific kind of activity within a time window — pair with summary_categories).\n"
    '  - strategy: "How did I solve this kind of bug last time?" / "之前那套部署流程是怎么走的".'
)


def _build_summary_categories_description(plugin_projection_service: Optional[Any]) -> str:
    """Compose the ``summary_categories`` parameter description.

    The catalog is always derived from the live plugin projection service so the LLM
    never sees categories that are not actually registered by a loaded
    plugin. When no categories are available (early boot, no plugins
    contribute summary profiles), the description tells the model to omit
    the field rather than guess from a stale hint.
    """

    categories: list[str] = []
    if plugin_projection_service is not None:
        getter = getattr(plugin_projection_service, "iter_merged_summary_profiles", None)
        if callable(getter):
            try:
                merged = list(getter())
            except Exception:  # pragma: no cover - defensive
                merged = []
            for profile in merged:
                category = getattr(profile, "summary_category", None)
                if isinstance(category, str) and category and category not in categories:
                    categories.append(category)
    if categories:
        catalog = ", ".join(categories)
        return (
            "Optional summary category filter for activity_summary or summary modes. "
            f"Available categories in this deployment: {catalog}. "
            "Pick the one that matches the user's activity. "
            "Omit this field if none of the available categories clearly fit; "
            "the retrieval pipeline will still rank candidates across all sources."
        )
    return (
        "Optional summary category filter for activity_summary or summary modes. "
        "No category profiles are currently registered in this deployment. "
        "Omit this field; the retrieval pipeline will rank candidates across "
        "all available sources."
    )


def _query_parameter() -> ToolParameter:
    return ToolParameter(
        name="query",
        type=ParameterType.STRING,
        description=(
            "The user's memory question, passed through in full and verbatim. "
            "Keep the ENTIRE question — do NOT distill it to a topic, drop clauses, "
            "or split a multi-part / relational question into pieces. "
            "Relational and multi-hop questions (e.g. 'albums of the singer I like', "
            "'my coworker's boss') must be passed whole; the memory engine resolves the "
            "hops itself. Match the user's language."
        ),
        required=True,
    )


def _time_range_parameter() -> ToolParameter:
    return ToolParameter(
        name="time_range",
        type=ParameterType.OBJECT,
        description=(
            'Optional time constraint. Use {"as_of": ISO8601|unix_seconds|common_date_text} '
            "for the state at one exact historical point; "
            'use {"relative": "<n>d|<n>h|<n>w"} '
            '(e.g. {"relative": "7d"} for last week) or '
            '{"start": ISO8601|unix_seconds|common_date_text, "end": ISO8601|unix_seconds|common_date_text}. '
            "Common date text examples: YYYY/MM/DD, YYYY-MM-DD, YYYY-MM-DD HH:MM:SS. "
            "Date-only end boundaries expand to the end of that day. "
            "Omit when the user's intent is "
            "lifetime/profile lookup."
        ),
        required=False,
    )


def _query_mode_parameter() -> ToolParameter:
    return ToolParameter(
        name="query_mode",
        type=ParameterType.STRING,
        description=(
            "Pick the retrieval mode by the SHAPE of the answer the user wants. "
            "Use 'cross_session' when they want to ENUMERATE multiple facts/items "
            "(e.g. 'which cafes have I been to', 'list the repos I cloned'). "
            "'current_state' for a single current value/preference; "
            "'episode_recall' for a narrative of what happened in a session; "
            "'experience_recall' for a coherent remembered period/project/trip; "
            "'temporal_compare' for before/after; 'summary'/'activity_summary' for "
            "digests; 'strategy' for how-to/procedures; 'exact_fact' for a single "
            "specific fact. If unsure, omit it and the system falls back to "
            "heuristic detection."
        ),
        required=False,
        enum=[
            "exact_fact",
            "current_state",
            "episode_recall",
            "experience_recall",
            "cross_session",
            "temporal_compare",
            "summary",
            "activity_summary",
            "strategy",
        ],
    )


def _summary_categories_parameter(plugin_projection_service: Optional[Any]) -> ToolParameter:
    return ToolParameter(
        name="summary_categories",
        type=ParameterType.ARRAY,
        array_item_type=ParameterType.STRING,
        description=_build_summary_categories_description(plugin_projection_service),
        required=False,
    )


def _limit_parameter() -> ToolParameter:
    return ToolParameter(
        name="limit",
        type=ParameterType.INTEGER,
        description="Maximum number of results to return.",
        required=False,
        default=20,
        min_value=1,
        max_value=100,
    )


def _conversation_context_parameter() -> ToolParameter:
    return ToolParameter(
        name="conversation_context",
        type=ParameterType.ARRAY,
        array_item_type=ParameterType.OBJECT,
        description=(
            "Optional. Recent conversation turns (each {role, content, timestamp}) "
            "providing context for indexical references like '当时'/'我说'/'just now'. "
            "Auto-injected by the runtime — callers should not need to populate this manually."
        ),
        required=False,
    )


def _memory_query_parameters(
    plugin_projection_service: Optional[Any],
) -> list[ToolParameter]:
    # Account selectors are resolved and authorized by the host coordinator.
    return [
        _query_parameter(),
        ToolParameter(name="source_scope", type=ParameterType.OBJECT, required=False,
            description="Optional explicit source restriction: domain (mail/calendar/notes), provider (gmail/qq), account (connection name or email), object_id or thread_id. Omit when the user did not name a source. Never invent identifiers."),
        ToolParameter(name="retrieval_policy", type=ParameterType.STRING, required=False,
            default="auto", enum=["auto", "memory_only", "verify_source"],
            description="auto recalls memory and checks relevant connected sources when needed; memory_only never queries sources; verify_source explicitly verifies the source now."),
        _time_range_parameter(),
        _query_mode_parameter(),
        _summary_categories_parameter(plugin_projection_service),
        _limit_parameter(),
        _conversation_context_parameter(),
    ]


def _memory_query_metadata() -> Dict[str, Any]:
    return {
        "task_intents": ["recall_context"],
        "domains": ["memory"],
        "operations": ["recall", "verify"],
        "query_shapes": ["prior_session", "user_preference", "historical_fact"],
        "followed_by": [],
        "avoid_task_intents": ["explore_codebase", "research_external"],
        "cost": "medium",
        "tool_hint": "Use for personal information, conversations, preferences, mail and connected sources. Set source_scope only when the user names a source; auto verifies relevant sources when retained evidence is insufficient or current state is needed.",
    }


class MemoryQueryTool(Tool):
    """Tool for querying memories across L0-L4."""

    def _init_schema(self) -> None:
        """Initialize tool schema with a static fallback description.

        The schema is rebuilt lazily inside :meth:`get_schema` / :meth:`get_info`
        once the plugin projection service binding is available so the
        ``summary_categories`` description reflects the live catalog.
        """
        self._schema_built_with_plugin_projection_service = False
        self.schema = self._build_schema(plugin_projection_service=None)

    def _build_schema(self, *, plugin_projection_service: Optional[Any]) -> ToolSchema:
        schema = ToolSchema(
            name="memory_query",
            description=(
                "Search personal information through one entry: retained memory and relevant connected sources, including mail. "
                "Use this tool for questions about prior conversations, activities, relationships, "
                "user preferences, personal facts, mail, current source state, summaries, or learned execution experience. "
                "The host checks freshness and coverage. Preserve source restrictions and do not infer absence from incomplete evidence."
            ),
            category="memory",
            parameters=_memory_query_parameters(plugin_projection_service),
            tags=["memory", "search", "history"],
            effect_replay_policy="read_only",
            timeout=60,
            metadata=_memory_query_metadata(),
        )

        from magi_plugin_sdk.source_query import SourceScope
        schema.input_schema = schema.json_input_schema()
        schema.input_schema["properties"]["source_scope"] = SourceScope.model_json_schema()
        return schema

    def _maybe_refresh_schema(self) -> None:
        """Rebuild the schema once the plugin projection service is bound.

        Called from :meth:`get_schema` / :meth:`get_info` so the description
        text reflects the live ``summary_categories`` catalog. Idempotent and
        cheap once refreshed.
        """
        if self._schema_built_with_plugin_projection_service:
            return
        try:
            plugin_projection_service = resolve_plugin_projection_service()
        except RuntimeError:
            return
        self.schema = self._build_schema(
            plugin_projection_service=plugin_projection_service,
        )
        self._schema_built_with_plugin_projection_service = True

    def get_schema(self) -> ToolSchema:
        self._maybe_refresh_schema()
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        self._maybe_refresh_schema()
        return super().get_info()

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute a hybrid retrieval query."""
        try:
            mq = self._resolve_memory_query_port(context)
            if isinstance(mq, ToolResult):
                return mq
            request = self._build_memory_query_request(mq, parameters, context)
            personal = context.capabilities.personal_retrieval
            if personal is None:
                return ToolResult(success=False, error="Personal retrieval is unavailable", error_code="CAPABILITY_UNAVAILABLE")
            data = await personal.retrieve(request,
                source_scope=parameters.get("source_scope") or {},
                retrieval_policy=parameters.get("retrieval_policy", "auto"), context=context)
            return ToolResult(success=True, data=data)

        except Exception as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code="EXECUTION_ERROR",
            )

    @staticmethod
    def _resolve_memory_query_port(context: ToolExecutionContext) -> Any | ToolResult:
        mq = context.capabilities.memory_query if context.capabilities else None
        if mq is None:
            return ToolResult(
                success=False,
                error="memory_query capability port is not available",
                error_code="CAPABILITY_UNAVAILABLE",
            )
        return mq

    def _build_memory_query_request(
        self,
        mq: Any,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> Any:
        user_id = context.invocation.principal_id if context.invocation else context.env_vars.get("user_id")
        session_id = parameters.get("session_id")
        current_user_text = context.env_vars.get("current_user_text") or None
        return mq.build_query(
            query=parameters["query"],
            user_id=user_id,
            session_id=session_id,
            time_range=parameters.get("time_range", {}),
            query_mode=parameters.get("query_mode"),
            source_filters=[],
            domain_filters=parameters.get("domains", []) or [],
            summary_categories=parameters.get("summary_categories", []) or [],
            context_signals={
                "workspace_path": context.env_vars.get("memory_context_workspace") or None,
                "user_text": current_user_text or parameters["query"],
                "task_category": context.env_vars.get("intent") or "",
            },
            limit=parameters.get("limit", 20),
            exclude_user_text=current_user_text,
            conversation_context=self._build_conversation_context(mq, parameters),
        )

    @staticmethod
    def _build_conversation_context(mq: Any, parameters: Dict[str, Any]) -> Any | None:
        raw_context = parameters.get("conversation_context") or []
        if not raw_context:
            return None

        turns = []
        for item in raw_context:
            if not isinstance(item, dict):
                continue
            if not {"role", "content", "timestamp"} <= item.keys():
                continue
            try:
                turns.append(
                    mq.make_conversation_turn(
                        role=item["role"],
                        content=item["content"],
                        timestamp=float(item["timestamp"]),
                    )
                )
            except (TypeError, ValueError):
                continue
        return turns or None

    def is_ready(self) -> bool:
        """Check if tool is ready to use.

        Intentional behaviour change (Phase 2 cluster-G migration):
        Previously this method returned False when the memory service was
        unavailable, causing the tool to be hidden from the LLM entirely.
        It now always returns True so the tool is always advertised.

        Rationale: the port indirection introduced by the MemoryQueryPort
        adapter means we cannot cheaply probe the underlying service at
        list-time without triggering a full service initialisation.  Instead,
        unavailability is reported as an execute-time error ToolResult
        (CAPABILITY_UNAVAILABLE / EXECUTION_ERROR) rather than hiding the
        tool.  This is a deliberate degraded-gracefully trade-off.
        """
        return True
