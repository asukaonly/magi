"""Memory query tool for retrieving memories across the rewritten L0-L4 layers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from ...memory.hybrid_retrieval import build_query
from ...memory.hybrid_retrieval.models import ConversationTurn
from ...memory.provider import get_hybrid_retrieval_service
from ...plugins.provider import resolve_plugin_manager
from ...memory.retrieval_projection import project_historical_recall
from ..schema import Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema, ParameterType


_QUERY_MODE_DESCRIPTION = (
    "The retrieval mode that best matches the user's intent. Pick exactly one. "
    "Examples:\n"
    "  - exact_fact: \"What's my default editor?\" / \"我喜欢什么音乐\" / \"我爸的电话\".\n"
    "  - current_state: \"What am I working on right now?\" / \"我现在的项目是什么\".\n"
    "  - episode_recall: \"What did I do at 3pm yesterday?\" / \"上周二的会议讨论了什么\".\n"
    "  - cross_session: \"How many times did I talk about X?\" / \"列出所有讨论过 X 的会话\".\n"
    "  - temporal_compare: \"How has my code style changed?\" / \"和上个月相比我看的网站有什么变化\".\n"
    "  - summary: \"Recap what I did last week\" / \"总结一下我上周\" (broad period recap, multiple kinds of activity).\n"
    "  - activity_summary: \"What did I browse yesterday?\" / \"我最近在 Chrome 上看什么\" / \"我这周听了什么音乐\" "
    "(one specific kind of activity within a time window — pair with summary_categories).\n"
    "  - strategy: \"How did I solve this kind of bug last time?\" / \"之前那套部署流程是怎么走的\"."
)


def _build_summary_categories_description(plugin_manager: Optional[Any]) -> str:
    """Compose the ``summary_categories`` parameter description.

    The catalog is always derived from the live plugin manager so the LLM
    never sees categories that are not actually registered by a loaded
    plugin. When no categories are available (early boot, no plugins
    contribute summary profiles), the description tells the model to omit
    the field rather than guess from a stale hint.
    """

    categories: list[str] = []
    if plugin_manager is not None:
        getter = getattr(plugin_manager, "iter_merged_summary_profiles", None)
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


class MemoryQueryTool(Tool):
    """Tool for querying memories across L0-L4."""

    def _init_schema(self) -> None:
        """Initialize tool schema with a static fallback description.

        The schema is rebuilt lazily inside :meth:`get_schema` / :meth:`get_info`
        once the plugin manager binding is available so the
        ``summary_categories`` description reflects the live catalog.
        """
        self._schema_built_with_plugin_manager = False
        self._service: Optional[Any] = None
        self.schema = self._build_schema(plugin_manager=None)

    def _build_schema(self, *, plugin_manager: Optional[Any]) -> ToolSchema:
        return ToolSchema(
            name="memory_query",
            description=(
                "Retrieve structured memory context from the lifecycle-based memory system. "
                "Use this tool for questions about prior conversations, activities, relationships, "
                "user preferences, personal facts, customized settings, summaries, or learned execution experience."
            ),
            category="memory",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The memory question or recall intent.",
                    required=True,
                ),
                ToolParameter(
                    name="time_range",
                    type=ParameterType.OBJECT,
                    description=(
                        "Optional time-range constraint. Either {\"relative\": \"<n>d|<n>h|<n>w\"} "
                        "(e.g. {\"relative\": \"7d\"} for last week) or "
                        "{\"start\": ISO8601|unix_seconds|common_date_text, \"end\": ISO8601|unix_seconds|common_date_text}. "
                        "Common date text examples: YYYY/MM/DD, YYYY-MM-DD, YYYY-MM-DD HH:MM:SS. "
                        "Date-only end boundaries expand to the end of that day. "
                        "Omit when the user's intent is "
                        "lifetime/profile lookup."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="sources",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description=(
                        "Optional source filter. Common values: 'chat' (conversation), "
                        "'timeline' (events from sensors like browsing/photos), 'profile' "
                        "(user preferences and persona facts), 'settings' (configured defaults), "
                        "'relationship' (people the user has talked about), 'worker' "
                        "(autonomous agent work)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="query_mode",
                    type=ParameterType.STRING,
                    description=_QUERY_MODE_DESCRIPTION,
                    required=True,
                    enum=["exact_fact", "current_state", "episode_recall", "cross_session", "temporal_compare", "summary", "activity_summary", "strategy"],
                ),
                ToolParameter(
                    name="summary_categories",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description=_build_summary_categories_description(plugin_manager),
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum number of results to return.",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=100,
                ),
                ToolParameter(
                    name="conversation_context",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.OBJECT,
                    description=(
                        "Optional. Recent conversation turns (each {role, content, timestamp}) "
                        "providing context for indexical references like '当时'/'我说'/'just now'. "
                        "Auto-injected by the runtime — callers should not need to populate this manually."
                    ),
                    required=False,
                ),
            ],
            tags=["memory", "search", "history"],
            timeout=30,
            metadata={
                "task_intents": ["recall_context"],
                "domains": ["memory"],
                "operations": ["recall", "verify"],
                "query_shapes": ["prior_session", "user_preference", "historical_fact"],
                "followed_by": [],
                "avoid_task_intents": ["explore_codebase", "research_external"],
                "cost": "medium",
                "tool_hint": "Use for prior conversations, preferences, historical actions, or learned procedures; prefer repo files for current code behavior.",
            },
        )

    def _maybe_refresh_schema(self) -> None:
        """Rebuild the schema once the plugin manager is bound.

        Called from :meth:`get_schema` / :meth:`get_info` so the description
        text reflects the live ``summary_categories`` catalog. Idempotent and
        cheap once refreshed.
        """
        if self._schema_built_with_plugin_manager:
            return
        try:
            plugin_manager = resolve_plugin_manager()
        except RuntimeError:
            return
        self.schema = self._build_schema(plugin_manager=plugin_manager)
        self._schema_built_with_plugin_manager = True

    def get_schema(self) -> ToolSchema:
        self._maybe_refresh_schema()
        return self.schema

    def get_info(self) -> Dict[str, Any]:
        self._maybe_refresh_schema()
        return super().get_info()

    def _get_service(self):
        """Return an initialized retrieval service when runtime memory is available."""
        self._service = get_hybrid_retrieval_service()
        return self._service

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Execute a hybrid retrieval query."""
        try:
            user_id = parameters.get("user_id") or context.env_vars.get("user_id")
            # Persistent memory recall should not inherit the current chat session
            # unless a caller explicitly opts into session-local lookup.
            session_id = parameters.get("session_id")
            current_user_text = context.env_vars.get("current_user_text") or None
            # Parse incoming conversation_context (list of dicts → list[ConversationTurn]).
            # Auto-injected by the runtime for indexical reference resolution; tolerant
            # of malformed entries (skip items missing required keys).
            raw_context = parameters.get("conversation_context") or []
            conversation_context: Optional[list[ConversationTurn]] = None
            if raw_context:
                turns: list[ConversationTurn] = []
                for item in raw_context:
                    if not isinstance(item, dict):
                        continue
                    if not {"role", "content", "timestamp"} <= item.keys():
                        continue
                    try:
                        turns.append(
                            ConversationTurn(
                                role=item["role"],
                                content=item["content"],
                                timestamp=float(item["timestamp"]),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
                if turns:
                    conversation_context = turns
            request = build_query(
                query=parameters["query"],
                user_id=user_id,
                session_id=session_id,
                time_range=parameters.get("time_range", {}),
                query_mode=parameters.get("query_mode"),
                source_filters=parameters.get("sources", []) or [],
                domain_filters=parameters.get("domains", []) or [],
                summary_categories=parameters.get("summary_categories", []) or [],
                limit=parameters.get("limit", 20),
                exclude_user_text=current_user_text,
                conversation_context=conversation_context,
            )
            payload = await self._get_service().query(request)
            payload_dict = asdict(payload) if hasattr(payload, "__dataclass_fields__") else {
                "l0_workbench": getattr(payload, "l0_workbench", []),
                "l1_events": getattr(payload, "l1_events", []),
                "l1_evidence_bundles": getattr(payload, "l1_evidence_bundles", []),
                "l1_timeline_summary": getattr(payload, "l1_timeline_summary", []),
                "l2_entity_cards": getattr(payload, "l2_entity_cards", []),
                "l2_relationships": getattr(payload, "l2_relationships", []),
                "l2_assertions": getattr(payload, "l2_assertions", []),
                "l3_reflections": getattr(payload, "l3_reflections", []),
                "l4_procedures": getattr(payload, "l4_procedures", []),
                "trace": getattr(payload, "trace", {}),
            }
            try:
                plugin_manager = resolve_plugin_manager()
            except RuntimeError:
                plugin_manager = None
            historical_recall = asdict(
                project_historical_recall(
                    payload=payload_dict,
                    request=request,
                    plugin_manager=plugin_manager,
                )
            )
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
        except Exception as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                error_code="EXECUTION_ERROR",
            )

    def is_ready(self) -> bool:
        """Check if tool is ready to use."""
        try:
            self._get_service()
        except RuntimeError:
            return False
        return True
