"""Unit tests for MemoryQueryTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMemoryQueryTool:
    """Tests for MemoryQueryTool."""

    def test_tool_initializes_without_runtime_memory_binding(self, monkeypatch):
        """Should allow schema initialization before unified memory is bound."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        def _raise_uninitialized() -> None:
            raise RuntimeError("hybrid_retrieval_service binding is not initialized")

        monkeypatch.setattr(memory_query_module, "require_hybrid_retrieval_service", _raise_uninitialized)

        tool = MemoryQueryTool()

        assert tool.get_schema().name == "memory_query"
        assert tool._service is None

    def test_tool_schema_definition(self):
        """Should have proper schema definition."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        assert schema.name == "memory_query"
        assert "memory" in schema.category.lower()
        assert len(schema.parameters) >= 2

    def test_tool_parameters(self):
        """Should require query while keeping query_mode optional."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        param_names = [p.name for p in schema.parameters]
        assert "query" in param_names
        assert "time_range" in param_names
        assert "sources" in param_names
        assert "recall_intent" in param_names
        assert "query_mode" in param_names

        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True
        time_range_param = next(p for p in schema.parameters if p.name == "time_range")
        assert time_range_param.required is False
        assert "user preferences" in schema.description
        assert "personal facts" in schema.description
        assert "customized settings" in schema.description

    def test_tool_uses_runtime_hybrid_retrieval_binding(self, monkeypatch):
        """Should resolve the shared runtime retrieval service."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        monkeypatch.setattr(memory_query_module, "require_hybrid_retrieval_service", lambda: fake_service)

        tool = MemoryQueryTool()

        assert tool._get_service() is fake_service

    def test_tool_get_service_raises_when_runtime_binding_is_missing(self, monkeypatch):
        """Should fail fast when the runtime retrieval service is not available."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        monkeypatch.setattr(
            memory_query_module,
            "require_hybrid_retrieval_service",
            lambda: (_ for _ in ()).throw(RuntimeError("hybrid_retrieval_service binding is not initialized")),
        )

        tool = MemoryQueryTool()

        with pytest.raises(RuntimeError, match="hybrid_retrieval_service"):
            tool._get_service()

    @pytest.mark.asyncio
    async def test_tool_execution(self, monkeypatch):
        """Should execute query and return a retrieval payload."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool
        from magi.tools.schema import ToolExecutionContext

        fake_service = MagicMock(name="retrieval_service")
        monkeypatch.setattr(memory_query_module, "require_hybrid_retrieval_service", lambda: fake_service)
        tool = MemoryQueryTool()
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[{"summary": "Current goal"}],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l3_reflections=[],
                l4_procedures=[],
                trace={"query_mode": "detail"},
            )
        )
        context = ToolExecutionContext(agent_id="test", task_id="test-task")

        result = await tool.execute({"query": "test query", "recall_intent": "preference_recall"}, context)

        assert result.success is True
        assert result.data["results"]["l0_workbench"][0]["summary"] == "Current goal"
        assert result.data["meta"]["query_mode"] == "detail"
        request = fake_service.query.await_args.args[0]
        assert request.recall_intent == "preference_recall"

    @pytest.mark.asyncio
    async def test_tool_to_claude_format(self):
        """Should export to Claude tool format."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        claude_format = tool.to_claude_format()

        assert claude_format["name"] == "memory_query"
        assert "input_schema" in claude_format
        assert "properties" in claude_format["input_schema"]
        assert claude_format["input_schema"]["properties"]["sources"]["type"] == "array"
        assert claude_format["input_schema"]["properties"]["sources"]["items"] == {"type": "string"}
