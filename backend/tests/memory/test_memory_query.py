"""Unit tests for memory query module."""
import pytest
import time
from datetime import datetime


class TestMemoryQueryRequest:
    """Tests for MemoryQueryRequest model."""

    def test_create_request_with_required_fields(self):
        """Should create request with query and time_range."""
        from magi.memory.query.models import MemoryQueryRequest

        request = MemoryQueryRequest(
            query="what did I browse yesterday",
            time_range={"relative": "1d"}
        )

        assert request.query == "what did I browse yesterday"
        assert request.time_range == {"relative": "1d"}
        assert request.data_types is None
        assert request.limit is None

    def test_create_request_with_all_fields(self):
        """Should create request with all optional fields."""
        from magi.memory.query.models import MemoryQueryRequest

        request = MemoryQueryRequest(
            query="find my notes",
            time_range={"start": 1700000000.0, "end": 1700100000.0},
            data_types=["note", "chat"],
            limit=10
        )

        assert request.query == "find my notes"
        assert request.data_types == ["note", "chat"]
        assert request.limit == 10

    def test_create_request_with_event_memory_fields(self):
        """Should accept source filters and query mode for event-centric retrieval."""
        from magi.memory.query.models import MemoryQueryRequest

        request = MemoryQueryRequest(
            query="what did I do yesterday",
            time_range={"relative": "1d"},
            sources=["git", "terminal"],
            query_mode="detail",
            limit=5,
        )

        assert request.sources == ["git", "terminal"]
        assert request.query_mode == "detail"
        assert request.limit == 5


class TestMemoryQueryResult:
    """Tests for MemoryQueryResult model."""

    def test_success_result(self):
        """Should create successful result with data."""
        from magi.memory.query.models import MemoryQueryResult

        result = MemoryQueryResult(
            status="success",
            data=[{"id": "1", "type": "browser_history", "content": {}}],
            query_meta={"layer": "L1", "total_count": 1}
        )

        assert result.status == "success"
        assert len(result.data) == 1
        assert result.confirm_prompt is None

    def test_confirm_required_result(self):
        """Should create result requiring user confirmation."""
        from magi.memory.query.models import MemoryQueryResult

        result = MemoryQueryResult(
            status="confirm_required",
            confirm_prompt="Please specify a time range for the search."
        )

        assert result.status == "confirm_required"
        assert result.confirm_prompt is not None
        assert result.data is None

    def test_query_meta_supports_event_retrieval_fields(self):
        """Should allow query metadata to expose event-centric retrieval information."""
        from magi.memory.query.models import MemoryQueryResult

        result = MemoryQueryResult(
            status="success",
            data=[],
            query_meta={
                "layers": ["L1", "L4"],
                "query_mode": "summary",
                "source_filters": ["git", "chat"],
            },
        )

        assert result.query_meta["layers"] == ["L1", "L4"]
        assert result.query_meta["query_mode"] == "summary"
        assert result.query_meta["source_filters"] == ["git", "chat"]


class TestRetrievalPlan:
    """Tests for RetrievalPlan contract."""

    def test_create_plan_with_ordered_layers(self):
        """Should store retrieval layers in priority order."""
        from magi.memory.query.models import RetrievalPlan

        plan = RetrievalPlan(
            layers=["L1", "L4"],
            query_mode="summary",
            source_filters=["git", "terminal"],
            time_range={"relative": "7d"},
            topic_query="programming",
            confidence=0.82,
            reasoning="Need raw events plus summaries.",
        )

        assert plan.layers == ["L1", "L4"]
        assert plan.query_mode == "summary"
        assert plan.source_filters == ["git", "terminal"]


class TestTypeHandler:
    """Tests for TypeHandler base class and registry."""

    def test_text_handler_extract(self):
        """Should extract content from text-based memories."""
        from magi.memory.query.handlers import TextHandler

        handler = TextHandler()
        result = handler.extract({
            "content": "Hello world",
            "summary": "A greeting"
        })

        assert result["content"] == "Hello world"
        assert result["summary"] == "A greeting"

    def test_browser_history_handler_extract(self):
        """Should extract core fields from browser history."""
        from magi.memory.query.handlers import BrowserHistoryHandler

        handler = BrowserHistoryHandler()
        result = handler.extract({
            "url": "https://example.com",
            "title": "Example Site",
            "visit_time": 1700000000.0,
            "page_content": "A" * 1000  # Long content
        })

        assert result["url"] == "https://example.com"
        assert result["title"] == "Example Site"
        assert len(result["snippet"]) <= 500  # Snippet is truncated

    def test_type_handler_registry_get_handler(self):
        """Should return correct handler for memory type."""
        from magi.memory.query.handlers import TypeHandlerRegistry

        registry = TypeHandlerRegistry()

        handler = registry.get_handler("browser_history")
        assert handler is not None
        assert "browser_history" in handler.supported_types

        handler = registry.get_handler("chat")
        assert handler is not None
        assert "chat" in handler.supported_types

    def test_type_handler_registry_unknown_type(self):
        """Should return None for unknown memory type."""
        from magi.memory.query.handlers import TypeHandlerRegistry

        registry = TypeHandlerRegistry()
        handler = registry.get_handler("unknown_type")
        assert handler is None

    def test_type_handler_registry_custom_handler(self):
        """Should register and retrieve custom handler."""
        from magi.memory.query.handlers import TypeHandler, TypeHandlerRegistry

        class CustomHandler(TypeHandler):
            @property
            def supported_types(self):
                return ["custom"]

            def extract(self, raw_data):
                return {"custom_field": raw_data.get("value")}

        registry = TypeHandlerRegistry()
        registry.register(CustomHandler())

        handler = registry.get_handler("custom")
        assert handler is not None
        result = handler.extract({"value": "test"})
        assert result["custom_field"] == "test"


class TestPrivacyGuard:
    """Tests for PrivacyGuard sensitivity checks."""

    def test_internal_data_allowed(self):
        """Should allow internal data types without confirmation."""
        from magi.memory.query.privacy import PrivacyGuard, PrivacyCheckResult

        guard = PrivacyGuard()
        result = guard.check(["browser_history", "chat"], {"query": "test"})

        assert result.allowed is True
        assert result.requires_confirmation is False
        assert result.blocked_types == []

    def test_sensitive_data_requires_confirmation(self):
        """Should require confirmation for sensitive data."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["private_diary"], {"query": "test"})

        assert result.allowed is True
        assert result.requires_confirmation is True
        assert result.confirm_prompt is not None

    def test_restricted_data_denied(self):
        """Should deny access to restricted data types."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["password"], {"query": "test"})

        assert result.allowed is False
        assert "password" in result.blocked_types

    def test_mixed_data_partial_block(self):
        """Should allow non-sensitive data while blocking restricted."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["browser_history", "password"], {"query": "test"})

        assert result.allowed is False
        assert "password" in result.blocked_types


class TestIntentRouter:
    """Tests for IntentRouter query routing."""

    def test_route_factual_query_to_l1(self):
        """Should route factual queries to L1."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("What time did I leave yesterday?", {"relative": "1d"})

        assert plan.primary_layer == "L1"
        assert plan.confidence > 0

    def test_route_concept_query_to_l3(self):
        """Should route concept/fuzzy queries to L3."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("Find my scattered thoughts on AI agents", {"relative": "7d"})

        # L3 is primary for concept retrieval
        assert plan.primary_layer == "L3"

    def test_route_trend_query_to_l4(self):
        """Should route trend/summary queries to L4."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("Summarize my job search over the past 6 months", {"relative": "180d"})

        assert plan.primary_layer == "L4"

    def test_low_confidence_includes_secondary_layers(self):
        """Should include secondary layers when confidence is low."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        # Ambiguous query that might need multiple layers
        plan = router.analyze("What was I working on recently?", {"relative": "7d"})

        # Either confidence is low OR secondary layers are populated
        assert plan.confidence < 0.8 or len(plan.secondary_layers) > 0

    def test_builds_event_detail_plan_for_yesterday_activity(self):
        """Should build a detail retrieval plan for historical activity review."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("What did I do yesterday?", {"relative": "1d"})

        assert plan.layers == ["L1"]
        assert plan.query_mode == "detail"
        assert plan.time_range == {"relative": "1d"}

    def test_infers_programming_sources_for_activity_review(self):
        """Should infer programming-related source filters from the query."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze(
            "Analyze what programming-related things I did yesterday",
            {"relative": "1d"},
        )

        assert "git" in plan.source_filters
        assert "terminal" in plan.source_filters
        assert "chrome_history" in plan.source_filters
        assert "chat" in plan.source_filters

    def test_builds_summary_mode_for_last_week_review(self):
        """Should infer summary mode for retrospective review requests."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("Summarize what I was doing last week", {"relative": "7d"})

        assert plan.query_mode == "summary"
        assert "L1" in plan.layers


import asyncio
from unittest.mock import AsyncMock, MagicMock


class TestMemoryQueryService:
    """Tests for MemoryQueryService orchestration."""

    @pytest.fixture
    def mock_layer_handlers(self):
        """Create mock layer handlers."""
        l1_handler = MagicMock()
        l1_handler.query = AsyncMock(return_value=[
            {"id": "1", "type": "browser_history", "timestamp": 1700000000.0, "data": {"url": "https://example.com"}}
        ])

        l3_handler = MagicMock()
        l3_handler.query = AsyncMock(return_value=[
            {"id": "2", "type": "chat", "timestamp": 1700001000.0, "data": {"content": "Hello"}}
        ])

        return {"L1": l1_handler, "L3": l3_handler}

    def test_missing_time_range_requires_confirmation(self):
        """Should return confirm_required when time_range is missing."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        service = MemoryQueryService()
        request = MemoryQueryRequest(
            query="test query",
            time_range={}  # Empty time range
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "confirm_required"
        assert "time range" in result.confirm_prompt.lower()

    def test_empty_results(self, mock_layer_handlers):
        """Should return empty status when no results found."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        # Handlers return empty
        for handler in mock_layer_handlers.values():
            handler.query = AsyncMock(return_value=[])

        service = MemoryQueryService(layer_handlers=mock_layer_handlers)
        request = MemoryQueryRequest(
            query="nonexistent",
            time_range={"relative": "1d"}
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "empty"

    def test_successful_query(self, mock_layer_handlers):
        """Should return success with processed results."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        service = MemoryQueryService(layer_handlers=mock_layer_handlers)
        request = MemoryQueryRequest(
            query="What did I browse yesterday?",
            time_range={"relative": "1d"}
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "success"
        assert len(result.data) >= 1
        assert result.query_meta is not None


class TestL1EventQueryHandler:
    """Tests for UnifiedMemoryStore-backed L1 event querying."""

    def test_filters_events_by_source_and_topic(self):
        """Should filter L1 events by requested sources and topic relevance."""
        from magi.memory.query.l1_handler import L1EventQueryHandler
        from magi.memory.query.models import MemoryQueryRequest, RetrievalPlan

        now = time.time()
        l1_raw = MagicMock()
        l1_raw.list_events = AsyncMock(return_value=[
            {
                "id": "git-1",
                "type": "TOOL_INVOKED",
                "timestamp": now - 3600,
                "source": "git",
                "data": {"message": "Committed memory query refactor", "files": ["router.py"]},
                "metadata": {"branch": "codex/memory"},
            },
            {
                "id": "calendar-1",
                "type": "TIMELINE_EVENT",
                "timestamp": now - 3500,
                "source": "calendar",
                "data": {"title": "Doctor appointment"},
                "metadata": {},
            },
        ])
        unified_memory = MagicMock()
        unified_memory.l1_raw = l1_raw

        handler = L1EventQueryHandler(unified_memory)
        request = MemoryQueryRequest(
            query="What programming-related things did I do yesterday?",
            time_range={"relative": "1d"},
            sources=["git", "terminal"],
            query_mode="detail",
        )
        plan = RetrievalPlan(
            layers=["L1"],
            query_mode="detail",
            source_filters=["git", "terminal"],
            time_range={"relative": "1d"},
            topic_query="programming",
            confidence=0.9,
            reasoning="Need L1 programming activity details.",
        )

        result = asyncio.run(handler.query(request, plan))

        assert len(result) == 1
        assert result[0]["source"] == "git"
        assert result[0]["event_id"] == "git-1"

    def test_returns_normalized_event_snippets(self):
        """Should return normalized fields for LLM-friendly event snippets."""
        from magi.memory.query.l1_handler import L1EventQueryHandler
        from magi.memory.query.models import MemoryQueryRequest, RetrievalPlan

        now = time.time()
        l1_raw = MagicMock()
        l1_raw.list_events = AsyncMock(return_value=[
            {
                "id": "term-1",
                "type": "TOOL_INVOKED",
                "timestamp": now - 1800,
                "source": "terminal",
                "data": {"command": "pytest tests/memory/test_memory_query.py", "result": "success"},
                "metadata": {"cwd": "/repo/backend"},
            }
        ])
        unified_memory = MagicMock()
        unified_memory.l1_raw = l1_raw

        handler = L1EventQueryHandler(unified_memory)
        request = MemoryQueryRequest(
            query="What commands did I run yesterday?",
            time_range={"relative": "1d"},
            sources=["terminal"],
            query_mode="detail",
        )
        plan = RetrievalPlan(
            layers=["L1"],
            query_mode="detail",
            source_filters=["terminal"],
            time_range={"relative": "1d"},
            topic_query="terminal",
            confidence=0.9,
            reasoning="Need terminal detail.",
        )

        result = asyncio.run(handler.query(request, plan))

        assert result[0]["event_id"] == "term-1"
        assert result[0]["event_type"] == "TOOL_INVOKED"
        assert result[0]["summary"]
        assert "details" in result[0]
        assert "raw_ref" in result[0]
