"""Memory query tool for retrieving memories across the rewritten L0-L4 layers."""

from __future__ import annotations

from dataclasses import asdict
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


def _context_scope_parameter() -> ToolParameter:
    return ToolParameter(
        name="context_scope",
        type=ParameterType.OBJECT,
        description=(
            "Optional resolved context for condition-scoped memories. Use only concrete "
            "dimensions known from the current conversation: project, activity, place, "
            "or person. Example: {\"project\": \"magi\", \"activity\": \"coding\"}. "
            "Omit it for ordinary global recall; an omitted scope never matches a "
            "scoped memory."
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
    # Source filters intentionally stay internal: user-facing memory_query searches
    # all sources and lets the retrieval engine rank by relevance.
    return [
        _query_parameter(),
        _time_range_parameter(),
        _query_mode_parameter(),
        _summary_categories_parameter(plugin_projection_service),
        _context_scope_parameter(),
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
        "tool_hint": "Use for prior conversations, preferences, historical actions, or learned procedures; prefer repo files for current code behavior.",
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
        return ToolSchema(
            name="memory_query",
            description=(
                "Retrieve structured memory context from the lifecycle-based memory system. "
                "Use this tool for questions about prior conversations, activities, relationships, "
                "user preferences, personal facts, customized settings, summaries, or learned execution experience."
            ),
            category="memory",
            parameters=_memory_query_parameters(plugin_projection_service),
            tags=["memory", "search", "history"],
            timeout=30,
            metadata=_memory_query_metadata(),
        )

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
            payload = await mq.query(request)
            payload_dict = self._payload_to_dict(payload)
            historical_recall = await self._project_historical_recall(
                mq=mq,
                payload_dict=payload_dict,
                request=request,
            )
            return self._build_success_result(
                historical_recall=historical_recall,
                payload_dict=payload_dict,
                context=context,
            )
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
        user_id = parameters.get("user_id") or context.env_vars.get("user_id")
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
            context_scope=dict(parameters.get("context_scope") or {}),
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

    @staticmethod
    def _payload_to_dict(payload: Any) -> Dict[str, Any]:
        if hasattr(payload, "__dataclass_fields__"):
            return asdict(payload)
        return {
            "l0_workbench": getattr(payload, "l0_workbench", []),
            "l1_events": getattr(payload, "l1_events", []),
            "l1_evidence_bundles": getattr(payload, "l1_evidence_bundles", []),
            "l1_timeline_summary": getattr(payload, "l1_timeline_summary", []),
            "l2_entity_cards": getattr(payload, "l2_entity_cards", []),
            "l2_relationships": getattr(payload, "l2_relationships", []),
            "l2_assertions": getattr(payload, "l2_assertions", []),
            "l2_experiences": getattr(payload, "l2_experiences", []),
            "l2_episodes": getattr(payload, "l2_episodes", []),
            "l3_reflections": getattr(payload, "l3_reflections", []),
            "l4_procedures": getattr(payload, "l4_procedures", []),
            "trace": getattr(payload, "trace", {}),
        }

    async def _project_historical_recall(
        self,
        *,
        mq: Any,
        payload_dict: Dict[str, Any],
        request: Any,
    ) -> Dict[str, Any]:
        canonical_names = await self._resolve_canonical_names(mq, payload_dict)
        return asdict(
            mq.project_historical_recall(
                payload=payload_dict,
                request=request,
                plugin_projection_service=self._resolve_projection_service(),
                canonical_names=canonical_names,
            )
        )

    @staticmethod
    def _resolve_projection_service() -> Any | None:
        try:
            return resolve_plugin_projection_service()
        except RuntimeError:
            return None

    async def _resolve_canonical_names(
        self,
        mq: Any,
        payload_dict: Dict[str, Any],
    ) -> dict[str, str] | None:
        db_path_attr = getattr(mq, "memory_db_path", None) or getattr(mq, "_memory_db_path", None)
        db_path = db_path_attr if isinstance(db_path_attr, str) else None
        if not db_path:
            return None

        entity_ids = self._collect_entity_ids(payload_dict)
        if not entity_ids:
            return {}
        return await mq.get_canonical_names(db_path, entity_ids)

    @staticmethod
    def _collect_entity_ids(payload_dict: Dict[str, Any]) -> set[str]:
        entity_ids: set[str] = set()
        for rel in payload_dict.get("l2_relationships") or []:
            if isinstance(rel, dict):
                if rel.get("subject_id"):
                    entity_ids.add(str(rel["subject_id"]))
                if rel.get("object_id"):
                    entity_ids.add(str(rel["object_id"]))
        for assertion in payload_dict.get("l2_assertions") or []:
            if isinstance(assertion, dict):
                if assertion.get("entity_id"):
                    entity_ids.add(str(assertion["entity_id"]))
                if assertion.get("target_entity_id"):
                    entity_ids.add(str(assertion["target_entity_id"]))
        for card in payload_dict.get("l2_entity_cards") or []:
            if isinstance(card, dict) and card.get("entity_id"):
                entity_ids.add(str(card["entity_id"]))

        trace_dict = payload_dict.get("trace") or {}
        if not isinstance(trace_dict, dict):
            return entity_ids
        l2_trace = trace_dict.get("l2_query_trace")
        if not isinstance(l2_trace, dict):
            return entity_ids
        for ent in l2_trace.get("resolved_entities") or []:
            if isinstance(ent, dict) and ent.get("entity_id"):
                entity_ids.add(str(ent["entity_id"]))
        return entity_ids

    @staticmethod
    def _build_success_result(
        *,
        historical_recall: Dict[str, Any],
        payload_dict: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "historical_recall": historical_recall,
                "debug": {
                    "retrieval_trace": payload_dict.get("trace", {}),
                    "agent_id": context.agent_id,
                },
            },
        )

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
