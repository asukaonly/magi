"""Memory query tool for retrieving memories across the rewritten L0-L4 layers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from ...core.runtime_bindings import require_hybrid_retrieval_service, require_plugin_manager
from ...memory.hybrid_retrieval import build_query
from ...memory.retrieval_projection import project_historical_recall
from ..schema import Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema, ParameterType


class MemoryQueryTool(Tool):
    """Tool for querying memories across L0-L4."""

    def _init_schema(self) -> None:
        """Initialize tool schema."""
        self.schema = ToolSchema(
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
                    description="Optional time range constraints for retrieval.",
                    required=False,
                ),
                ToolParameter(
                    name="sources",
                    type=ParameterType.ARRAY,
                    array_item_type=ParameterType.STRING,
                    description="Optional source filters such as ['chat', 'timeline', 'worker'].",
                    required=False,
                ),
                ToolParameter(
                    name="query_mode",
                    type=ParameterType.STRING,
                    description=(
                        "The retrieval mode that best matches the user's intent. Choose one: "
                        "exact_fact (specific facts, preferences, profile data), "
                        "current_state (what is currently true, present status), "
                        "episode_recall (what happened on a specific occasion), "
                        "cross_session (aggregation across multiple sessions — how many, which ones, all), "
                        "temporal_compare (before/after, changes over time), "
                        "summary (summarize or recap a period), "
                        "strategy (how-to, workflow, prior approach)."
                    ),
                    required=True,
                    enum=["exact_fact", "current_state", "episode_recall", "cross_session", "temporal_compare", "summary", "strategy"],
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
            ],
            tags=["memory", "search", "history"],
            timeout=30,
        )
        self._service: Optional[Any] = None

    def _get_service(self):
        """Return an initialized retrieval service when runtime memory is available."""
        self._service = require_hybrid_retrieval_service()
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
            request = build_query(
                query=parameters["query"],
                user_id=user_id,
                session_id=session_id,
                time_range=parameters.get("time_range", {}),
                query_mode=parameters.get("query_mode"),
                source_filters=parameters.get("sources", []) or [],
                domain_filters=parameters.get("domains", []) or [],
                limit=parameters.get("limit", 20),
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
                plugin_manager = require_plugin_manager()
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
