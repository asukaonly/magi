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
        """Should require query while keeping time_range optional."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        param_names = [p.name for p in schema.parameters]
        assert "query" in param_names
        assert "time_range" in param_names
        assert "sources" in param_names
        assert "query_mode" in param_names

        # query should be required
        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True
        time_range_param = next(p for p in schema.parameters if p.name == "time_range")
        assert time_range_param.required is False

    def test_tool_uses_runtime_unified_memory_for_l1_queries(self, monkeypatch):
        """Should build its service with a UnifiedMemoryStore-backed L1 handler."""
        import magi.tools.memory_query as memory_query_module
        from magi.tools.memory_query import MemoryQueryTool

        fake_unified_memory = MagicMock()
        fake_unified_memory.l1_raw = MagicMock()
        monkeypatch.setattr(memory_query_module, "get_unified_memory", lambda: fake_unified_memory)

        tool = MemoryQueryTool()

        assert "L1" in tool._service.layer_handlers
        assert tool._service.layer_handlers["L1"].__class__.__name__ == "L1EventQueryHandler"

    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Should execute query and return ToolResult when only query is provided."""
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
