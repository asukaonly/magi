"""Unit tests for memory query module."""
import pytest
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
