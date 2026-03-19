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
            raise RuntimeError("unified_memory binding is not initialized")

        monkeypatch.setattr(memory_query_module, "require_unified_memory", _raise_uninitialized)

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
        assert "query_mode" in param_names

        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True
        time_range_param = next(p for p in schema.parameters if p.name == "time_range")
        assert time_range_param.required is False

    def test_tool_uses_runtime_unified_memory_for_hybrid_queries(self, monkeypatch):
        """Should build its service with a HybridRetrievalService-backed runtime memory store."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_unified_memory = MagicMock()
        monkeypatch.setattr(memory_query_module, "require_unified_memory", lambda: fake_unified_memory)
        monkeypatch.setattr(memory_query_module, "require_scenario_llm_pool", lambda: None)

        tool = MemoryQueryTool()

        assert tool._service.__class__.__name__ == "HybridRetrievalService"

    def test_tool_passes_llm_provider_bridge_into_hybrid_retrieval_service(self, monkeypatch):
        """Should wire a provider bridge for retrieval intent decisions when scenario pool is available."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.config.models import LLMScenario
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_unified_memory = MagicMock()
        fake_adapter = MagicMock()
        fake_scenario_pool = MagicMock()
        fake_scenario_pool.get.return_value = fake_adapter
        captured = {}

        class _FakeHybridRetrievalService:
            def __init__(self, unified_memory, *, llm_provider_bridge=None, config=None):
                captured["unified_memory"] = unified_memory
                captured["llm_provider_bridge"] = llm_provider_bridge
                captured["config"] = config

        monkeypatch.setattr(memory_query_module, "require_unified_memory", lambda: fake_unified_memory)
        monkeypatch.setattr(memory_query_module, "require_scenario_llm_pool", lambda: fake_scenario_pool)
        monkeypatch.setattr(memory_query_module, "HybridRetrievalService", _FakeHybridRetrievalService)

        tool = MemoryQueryTool()

        assert captured["unified_memory"] is fake_unified_memory
        assert captured["llm_provider_bridge"] is not None
        fake_scenario_pool.get.assert_called_once_with(LLMScenario.CONTEXT_DECIDER)
        assert getattr(captured["llm_provider_bridge"], "llm", None) is fake_adapter
        assert tool._service is not None

    def test_tool_rebuilds_service_when_runtime_memory_binding_changes(self, monkeypatch):
        """Should rebuild the retrieval service if the bound unified memory instance changes."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        first_memory = MagicMock(name="first_memory")
        second_memory = MagicMock(name="second_memory")
        current = {"memory": first_memory}

        class _FakeHybridRetrievalService:
            def __init__(self, unified_memory, *, llm_provider_bridge=None, config=None):
                self._memory = unified_memory

        monkeypatch.setattr(memory_query_module, "require_unified_memory", lambda: current["memory"])
        monkeypatch.setattr(memory_query_module, "require_scenario_llm_pool", lambda: None)
        monkeypatch.setattr(memory_query_module, "HybridRetrievalService", _FakeHybridRetrievalService)

        tool = MemoryQueryTool()
        assert tool._service is not None
        assert tool._service._memory is first_memory

        current["memory"] = second_memory

        service = tool._get_service()
        assert service._memory is second_memory

    @pytest.mark.asyncio
    async def test_tool_execution(self, monkeypatch):
        """Should execute query and return a retrieval payload."""
        import magi.tools.builtin.memory_query_tool as memory_query_module
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool
        from magi.tools.schema import ToolExecutionContext

        fake_unified_memory = MagicMock(name="runtime_memory")
        monkeypatch.setattr(memory_query_module, "require_unified_memory", lambda: fake_unified_memory)
        tool = MemoryQueryTool()
        tool._service = MagicMock()
        tool._service._memory = fake_unified_memory
        tool._service.query = AsyncMock(
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

        result = await tool.execute({"query": "test query"}, context)

        assert result.success is True
        assert result.data["results"]["l0_workbench"][0]["summary"] == "Current goal"
        assert result.data["meta"]["query_mode"] == "detail"

    @pytest.mark.asyncio
    async def test_tool_to_claude_format(self):
        """Should export to Claude tool format."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        claude_format = tool.to_claude_format()

        assert claude_format["name"] == "memory_query"
        assert "input_schema" in claude_format
        assert "properties" in claude_format["input_schema"]
