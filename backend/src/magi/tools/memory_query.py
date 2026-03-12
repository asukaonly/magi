"""Memory query tool for retrieving memories across L1-L5 layers."""
from typing import Any, Dict, List

from .schema import Tool, ToolParameter, ParameterType, ToolResult, ToolExecutionContext, ToolSchema
from ..memory.query import MemoryQueryService, MemoryQueryRequest


class MemoryQueryTool(Tool):
    """Tool for querying memories across L1-L5 layers."""

    def _init_schema(self) -> None:
        """Initialize tool schema."""
        self.schema = ToolSchema(
            name="memory_query",
            description="Retrieve memories from L1-L5 layers. Use this tool when the user asks about their past activities, browsing history, conversations, or any historical data. Supports intelligent routing across memory layers.",
            category="memory",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The search query describing what memories to retrieve (e.g., 'what I browsed yesterday', 'my notes about AI')",
                    required=True,
                ),
                ToolParameter(
                    name="time_range",
                    type=ParameterType.OBJECT,
                    description="Time range for the search. Must include 'relative' (e.g., '1d', '7d', '1M') or 'start'/'end' timestamps.",
                    required=True,
                ),
                ToolParameter(
                    name="data_types",
                    type=ParameterType.ARRAY,
                    description="Optional filter for memory types (e.g., ['browser_history', 'chat', 'note'])",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum number of results to return",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=100,
                ),
            ],
            examples=[
                {
                    "input": {
                        "query": "What websites did I visit yesterday?",
                        "time_range": {"relative": "1d"},
                        "data_types": ["browser_history"]
                    },
                    "output": "Returns browser history from yesterday",
                },
                {
                    "input": {
                        "query": "Find my notes about machine learning from last week",
                        "time_range": {"relative": "7d"},
                        "data_types": ["note"]
                    },
                    "output": "Returns notes containing 'machine learning' from last week",
                }
            ],
            tags=["memory", "search", "history"],
            timeout=30,
        )

        self._service = MemoryQueryService()

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute memory query."""
        try:
            request = MemoryQueryRequest(
                query=parameters["query"],
                time_range=parameters.get("time_range", {}),
                data_types=parameters.get("data_types"),
                limit=parameters.get("limit"),
            )

            result = await self._service.query(request)

            if result.status == "success":
                return ToolResult(
                    success=True,
                    data={
                        "results": result.data,
                        "meta": result.query_meta,
                    }
                )
            elif result.status == "confirm_required":
                return ToolResult(
                    success=False,
                    error=result.confirm_prompt,
                    error_code="CONFIRM_REQUIRED",
                )
            elif result.status == "empty":
                return ToolResult(
                    success=True,
                    data={"results": [], "meta": result.query_meta},
                )
            else:  # denied
                return ToolResult(
                    success=False,
                    error=result.confirm_prompt,
                    error_code="ACCESS_DENIED",
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR",
            )

    def is_ready(self) -> bool:
        """Check if tool is ready to use."""
        # Memory query is always available
        return True
