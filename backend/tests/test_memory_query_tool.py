"""Unit tests for MemoryQueryTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMemoryQueryTool:
    """Tests for MemoryQueryTool."""

    def test_tool_schema_definition(self):
        """Should have proper schema definition."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        assert schema.name == "memory_query"
        assert "memory" in schema.category.lower()
        assert len(schema.parameters) >= 2  # query + time_range at minimum

    def test_tool_parameters(self):
        """Should have required query and time_range parameters."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        param_names = [p.name for p in schema.parameters]
        assert "query" in param_names
        assert "time_range" in param_names

        # query should be required
        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True

    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Should execute query and return ToolResult."""
        from magi.tools.memory_query import MemoryQueryTool
        from magi.tools.schema import ToolExecutionContext

        tool = MemoryQueryTool()
        context = ToolExecutionContext(
            agent_id="test",
            task_id="test-task"
        )

        result = await tool.execute(
            {
                "query": "test query",
                "time_range": {"relative": "1d"}
            },
            context
        )

        # Result should be a ToolResult
        assert hasattr(result, "success")
        assert hasattr(result, "data")

    @pytest.mark.asyncio
    async def test_tool_to_claude_format(self):
        """Should export to Claude tool format."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        claude_format = tool.to_claude_format()

        assert claude_format["name"] == "memory_query"
        assert "input_schema" in claude_format
        assert "properties" in claude_format["input_schema"]
