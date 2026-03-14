"""Memory query tool for retrieving memories across L1-L5 layers."""
from typing import Any, Dict, Optional

from ..agent import get_unified_memory
from ..core.logger import Loggers
from ..memory.query.l1_handler import L1EventQueryHandler

from .schema import Tool, ToolParameter, ParameterType, ToolResult, ToolExecutionContext, ToolSchema
from ..memory.query import MemoryQueryService, MemoryQueryRequest

log = Loggers.memory()


class MemoryQueryTool(Tool):
    """Tool for querying memories across L1-L5 layers."""

    def _init_schema(self) -> None:
        """Initialize tool schema."""
        self.schema = ToolSchema(
            name="memory_query",
            description=(
                "Retrieve historical event memory from UnifiedMemoryStore. Use this tool when the user asks "
                "about past activities, prior work, earlier conversations, browser history, git activity, "
                "terminal commands, or other historical behavior. You may pass only the raw query when unsure; "
                "the service will infer time range, sources, and retrieval mode."
            ),
            category="memory",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The historical activity or memory question to retrieve evidence for.",
                    required=True,
                ),
                ToolParameter(
                    name="time_range",
                    type=ParameterType.OBJECT,
                    description="Optional time range hint. Use relative or absolute boundaries when the user states them.",
                    required=False,
                ),
                ToolParameter(
                    name="sources",
                    type=ParameterType.ARRAY,
                    description="Optional source filters such as ['chrome_history', 'git', 'chat', 'terminal'].",
                    required=False,
                ),
                ToolParameter(
                    name="query_mode",
                    type=ParameterType.STRING,
                    description="Optional retrieval mode hint such as 'detail', 'summary', or 'experience'.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum number of results to return",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=500,
                ),
            ],
            examples=[
                {
                    "input": {
                        "query": "What websites did I visit yesterday?",
                        "time_range": {"relative": "1d"},
                        "sources": ["chrome_history"]
                    },
                    "output": "Returns browser history from yesterday",
                },
                {
                    "input": {
                        "query": "What programming-related things did I do yesterday?",
                        "time_range": {"relative": "7d"},
                        "sources": ["git", "terminal", "chat", "chrome_history"],
                        "query_mode": "detail"
                    },
                    "output": "Returns normalized event snippets for programming-related activity",
                }
            ],
            tags=["memory", "search", "history"],
            timeout=30,
        )

        # Service will be initialized lazily on first use
        self._service: Optional[MemoryQueryService] = None

    def _build_service(self) -> MemoryQueryService:
        unified_memory = None
        try:
            unified_memory = get_unified_memory()
            log.info("[MemoryQueryTool] get_unified_memory success", has_memory=unified_memory is not None)
        except Exception as e:
            log.warning("[MemoryQueryTool] get_unified_memory failed", error=str(e))
            unified_memory = None

        layer_handlers: Dict[str, Any] = {}
        if unified_memory is not None:
            layer_handlers["L1"] = L1EventQueryHandler(unified_memory)
            log.info("[MemoryQueryTool] L1 handler registered")
        else:
            log.warning("[MemoryQueryTool] L1 handler NOT registered - unified_memory is None")
        return MemoryQueryService(layer_handlers=layer_handlers)

    def _ensure_service(self) -> MemoryQueryService:
        """Lazily initialize service on first use."""
        if self._service is None:
            self._service = self._build_service()
        return self._service

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute memory query."""
        try:
            service = self._ensure_service()

            request = MemoryQueryRequest(
                query=parameters["query"],
                time_range=parameters.get("time_range", {}),
                sources=parameters.get("sources"),
                query_mode=parameters.get("query_mode"),
                data_types=parameters.get("data_types"),
                limit=parameters.get("limit"),
            )

            log.info(
                "[MemoryQueryTool] execute input",
                query=request.query,
                time_range=request.time_range,
                sources=request.sources,
                query_mode=request.query_mode,
                limit=request.limit,
            )

            result = await service.query(request)

            log.info(
                "[MemoryQueryTool] execute output",
                status=result.status,
                result_count=len(result.data) if result.data else 0,
                query_meta=result.query_meta,
            )

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
