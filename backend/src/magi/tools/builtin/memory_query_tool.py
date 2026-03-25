"""Memory query tool for retrieving memories across the rewritten L0-L4 layers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from ...core.runtime_bindings import require_hybrid_retrieval_service
from ...memory.hybrid_retrieval import build_query
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
                    name="recall_intent",
                    type=ParameterType.STRING,
                    description="Optional recall intent hint (event_recall|preference_recall|profile_fact_recall|relationship_recall|workflow_reuse).",
                    required=False,
                    default=None,
                ),
                ToolParameter(
                    name="query_mode",
                    type=ParameterType.STRING,
                    description="Optional routing hint (detail|summary|experience|graph|strategy). When omitted, the intent decider selects the best layers automatically.",
                    required=False,
                    default=None,
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
            request = build_query(
                query=parameters["query"],
                user_id=parameters.get("user_id"),
                session_id=parameters.get("session_id"),
                time_range=parameters.get("time_range", {}),
                recall_intent=parameters.get("recall_intent"),
                query_mode=parameters.get("query_mode"),
                source_filters=parameters.get("sources", []) or [],
                domain_filters=parameters.get("domains", []) or [],
                limit=parameters.get("limit", 20),
            )
            payload = await self._get_service().query(request)
            payload_dict = asdict(payload) if hasattr(payload, "__dataclass_fields__") else {
                "l0_workbench": getattr(payload, "l0_workbench", []),
                "l1_events": getattr(payload, "l1_events", []),
                "l2_entity_cards": getattr(payload, "l2_entity_cards", []),
                "l2_relationships": getattr(payload, "l2_relationships", []),
                "l2_assertions": getattr(payload, "l2_assertions", []),
                "l3_reflections": getattr(payload, "l3_reflections", []),
                "l4_procedures": getattr(payload, "l4_procedures", []),
                "trace": getattr(payload, "trace", {}),
            }
            return ToolResult(
                success=True,
                data={
                    "results": payload_dict,
                    "meta": payload_dict["trace"],
                    "agent_id": context.agent_id,
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
