"""Memory query service for orchestrating retrieval across L1-L5 layers."""
from typing import Any, Dict, List, Optional

from .models import MemoryQueryRequest, MemoryQueryResult
from .handlers import TypeHandlerRegistry
from .privacy import PrivacyGuard
from .router import IntentRouter


class MemoryQueryService:
    """
    Main service for memory retrieval.
    Orchestrates routing, privacy, querying, and formatting.
    """

    def __init__(
        self,
        layer_handlers: Optional[Dict[str, Any]] = None,
        type_handlers: Optional[TypeHandlerRegistry] = None,
        privacy_guard: Optional[PrivacyGuard] = None,
    ):
        self.router = IntentRouter()
        self.privacy_guard = privacy_guard or PrivacyGuard()
        self.type_handlers = type_handlers or TypeHandlerRegistry()
        self.layer_handlers = layer_handlers or {}

    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        """
        Execute memory query with full pipeline.

        Pipeline:
        1. Validate time_range (require if missing)
        2. Privacy check
        3. Intent routing
        4. Parallel layer queries
        5. TypeHandler extraction
        6. Return formatted results

        Args:
            request: MemoryQueryRequest with query parameters

        Returns:
            MemoryQueryResult with status and data
        """
        # Step 1: Validate time range
        if not self._validate_time_range(request.time_range):
            return MemoryQueryResult(
                status="confirm_required",
                confirm_prompt="Please specify a time range for the search (e.g., 'yesterday', 'last week')."
            )

        # Step 2: Determine data types to query
        data_types = request.data_types or self._infer_data_types(request.query, request.sources)

        # Step 3: Privacy check
        privacy_result = self.privacy_guard.check(data_types, {"query": request.query})
        if not privacy_result.allowed:
            return MemoryQueryResult(
                status="denied",
                confirm_prompt=f"Access to {', '.join(privacy_result.blocked_types)} is restricted."
            )
        if privacy_result.requires_confirmation:
            return MemoryQueryResult(
                status="confirm_required",
                confirm_prompt=privacy_result.confirm_prompt
            )

        # Step 4: Intent routing
        routing_plan = self.router.analyze(request.query, request.time_range)

        # Step 5: Execute parallel queries
        raw_results = await self.router.execute(
            routing_plan,
            request,
            self.layer_handlers
        )

        # Step 6: Apply type handlers
        processed_results: List[Dict[str, Any]] = []
        for item in raw_results:
            memory_type = item.get("type")
            handler = self.type_handlers.get_handler(memory_type)

            if handler:
                raw_data = item.get("data", item)
                processed_results.append({
                    "id": item.get("id"),
                    "type": memory_type,
                    "timestamp": item.get("timestamp"),
                    "source": item.get("source"),
                    "content": handler.extract(raw_data),
                })
            else:
                # Fallback: return raw data
                processed_results.append(item)

        # Apply limit
        if request.limit and request.limit > 0:
            processed_results = processed_results[:request.limit]

        # Build query metadata
        query_meta = {
            "layers": list(routing_plan.layers),
            "layer": routing_plan.primary_layer,
            "secondary_layers": list(routing_plan.secondary_layers),
            "query_mode": routing_plan.query_mode,
            "source_filters": list(routing_plan.source_filters),
            "time_range": dict(routing_plan.time_range),
            "topic_query": routing_plan.topic_query,
            "confidence": routing_plan.confidence,
            "total_count": len(processed_results),
        }

        return MemoryQueryResult(
            status="success" if processed_results else "empty",
            data=processed_results if processed_results else None,
            query_meta=query_meta
        )

    def _validate_time_range(self, time_range: Dict[str, Any]) -> bool:
        """Check if time range is specified."""
        if not time_range:
            return False
        return bool(
            time_range.get("start") or
            time_range.get("end") or
            time_range.get("relative")
        )

    def _infer_data_types(self, query: str, sources: Optional[List[str]] = None) -> List[str]:
        """Infer relevant data types from query context."""
        if sources:
            mapped = []
            if "chrome_history" in sources:
                mapped.append("browser_history")
            if "chat" in sources:
                mapped.append("chat")
            if mapped:
                return mapped
        query_lower = query.lower()
        types: List[str] = []

        if any(kw in query_lower for kw in ["browse", "website", "page", "url", "浏览", "网页"]):
            types.append("browser_history")
        if any(kw in query_lower for kw in ["chat", "conversation", "talk", "对话", "聊天"]):
            types.append("chat")
        if any(kw in query_lower for kw in ["note", "笔记", "记录"]):
            types.append("note")

        # Default to common types if no specific inference
        if not types:
            types = ["browser_history", "chat", "note"]

        return types
