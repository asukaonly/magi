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
