"""Unit tests for MemoryQueryTool."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.core.tool_capabilities import ToolCapabilities
from _shared.personal_retrieval import personal_port


def _make_fake_mq(fake_service=None):
    """Build a fake MemoryQueryPort backed by an optional fake_service."""
    if fake_service is None:
        fake_service = MagicMock(name="retrieval_service")

    async def _query(req):
        return await fake_service.query(req)

    mq = MagicMock(name="memory_query_port")
    mq.build_query.side_effect = lambda **kwargs: _real_build_query(**kwargs)
    mq.query = AsyncMock(side_effect=_query)
    mq.get_canonical_names = AsyncMock(return_value={})
    mq.project_historical_recall.side_effect = _real_project
    mq.make_conversation_turn.side_effect = _real_make_turn
    # Expose service for assertions
    mq._fake_service = fake_service
    return mq


def _real_build_query(**kwargs):
    from magi.memory.hybrid_retrieval import build_query

    return build_query(**kwargs)


def _real_project(**kwargs):
    from magi.memory.retrieval_projection import project_historical_recall

    return project_historical_recall(**kwargs)


def _real_make_turn(**kwargs):
    from magi.memory.hybrid_retrieval.models import ConversationTurn

    return ConversationTurn(**kwargs)


def _make_context(fake_mq=None, **kwargs):
    from magi.tools.schema import ToolExecutionContext

    caps = ToolCapabilities(memory_query=fake_mq, personal_retrieval=personal_port(fake_mq))
    return ToolExecutionContext(agent_id="test", capabilities=caps, **kwargs)


class TestMemoryQueryTool:
    """Tests for MemoryQueryTool."""


    @pytest.mark.parametrize("format", ["anthropic", "openai"])
    def test_exported_schema_exposes_only_supported_optional_filters(self, format):
        from magi.agent.execution.function_calling import FunctionCallingOrchestrator
        from magi.tools.registry import ToolRegistry
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        if format == "anthropic":
            schema = MemoryQueryTool().to_claude_format()["input_schema"]
        else:
            registry = ToolRegistry()
            registry.register(MemoryQueryTool)
            schema = FunctionCallingOrchestrator(tool_registry=registry)._build_tools_parameter(
                ["memory_query"]
            )[0]["function"]["parameters"]
        assert schema["required"] == ["query"]
        props = schema["properties"]
        # Keep the essential prompt instruction at the exported tool boundary.
        assert "verbatim" in props["query"]["description"].lower()
        assert {key: value["type"] for key, value in props.items()} == {
            "query": "string",
            "source_scope": "object",
            "retrieval_policy": "string",
            "time_range": "object",
            "query_mode": "string",
            "summary_categories": "array",
            "limit": "integer",
            "conversation_context": "array",
        }
        assert props["conversation_context"]["items"] == {"type": "object"}
        assert props["summary_categories"]["items"] == {"type": "string"}
        assert set(props["query_mode"]["enum"]) == {
            "exact_fact",
            "current_state",
            "episode_recall",
            "experience_recall",
            "cross_session",
            "temporal_compare",
            "summary",
            "activity_summary",
            "strategy",
        }

    @pytest.mark.parametrize("categories", [None, [], ["browser_activity", "browser_activity"]])
    def test_schema_advertises_only_registered_summary_categories(self, monkeypatch, categories):
        from types import SimpleNamespace
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        service = (
            None
            if categories is None
            else SimpleNamespace(
                iter_merged_summary_profiles=lambda: [
                    SimpleNamespace(summary_category=c) for c in categories
                ]
            )
        )
        monkeypatch.setattr("magi.tools.builtin.memory_query_tool.resolve_plugin_projection_service", lambda: service)
        from magi.agent.execution.function_calling import FunctionCallingOrchestrator
        from magi.tools.registry import ToolRegistry
        registry = ToolRegistry()
        registry.register(MemoryQueryTool)
        schema = FunctionCallingOrchestrator(tool_registry=registry)._build_tools_parameter(["memory_query"])[0]["function"]["parameters"]
        description = schema["properties"]["summary_categories"]["description"]
        assert description.count("browser_activity") == (1 if categories else 0)
        assert "media_listening" not in description
        assert "coding_activity" not in description
        if not categories:
            assert "Omit this field" in description


    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Should execute query and return projected recall plus debug payloads."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[
                    {
                        "session": {"session_id": "session-1"},
                        "attention_items": [
                            {
                                "kind": "focus",
                                "summary": "The user is asking about weather preferences.",
                                "status": "active",
                            }
                        ],
                    }
                ],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[
                    {
                        "triple_id": "triple-1",
                        "subject_id": "user:local_user",
                        "predicate": "DISLIKES",
                        "object_id": "weather_state:humid",
                        "confidence": 0.97,
                        "status": "active",
                    }
                ],
                l2_assertions=[],
                l3_reflections=[],
                l4_procedures=[],
                trace={"query_mode": "detail", "primary_count": 1},
            )
        )
        fake_mq = _make_fake_mq(fake_service)
        fake_mq.get_canonical_names = AsyncMock(return_value={"weather_state:humid": "潮湿天气"})
        tool = MemoryQueryTool()
        context = _make_context(fake_mq=fake_mq, task_id="test-task")

        result = await tool.execute({"query": "test query", "query_mode": "exact_fact"}, context)

        assert result.success is True
        assert result.data["recall"]["summary"] == "你讨厌潮湿天气。"
        assert (
            result.data["recall"]["findings"][0]["statement"]
            == "local_user DISLIKES 潮湿天气"
        )
        fake_mq.get_canonical_names.assert_awaited_once_with(
            {"user:local_user", "weather_state:humid"}
        )
        assert result.data["debug"]["retrieval_trace"]["query_mode"] == "detail"
        request = fake_mq.query.await_args.args[0]
        assert request.query_mode == "exact_fact"

    @pytest.mark.asyncio
    async def test_tool_execution_uses_context_user_and_session(self):
        """Should inherit runtime user but not implicitly bind the chat session."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l2_assertions=[],
                l3_reflections=[],
                l4_procedures=[],
                trace={"query_mode": "detail"},
            )
        )
        fake_mq = _make_fake_mq(fake_service)
        tool = MemoryQueryTool()
        context = _make_context(
            fake_mq=fake_mq,
            env_vars={"user_id": "local_user", "session_id": "session-123"},
        )

        result = await tool.execute(
            {"query": "我喜欢什么天气", "query_mode": "exact_fact"}, context
        )

        assert result.success is True
        request = fake_mq.query.await_args.args[0]
        assert request.user_id == "local_user"
        assert request.session_id is None

    @pytest.mark.asyncio
    async def test_tool_execution_passes_context_signals_and_as_of_time(self):
        """Trusted local signals and point-in-time intent must reach retrieval."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l2_assertions=[],
                l3_reflections=[],
                l4_procedures=[],
                trace={"query_mode": "exact_fact"},
            )
        )
        fake_mq = _make_fake_mq(fake_service)
        tool = MemoryQueryTool()

        result = await tool.execute(
            {
                "query": "当时在 Magi 项目里我住在哪里",
                "query_mode": "exact_fact",
                "time_range": {"as_of": 1234.0},
            },
            _make_context(
                fake_mq=fake_mq,
                workspace="/tmp/magi",
                env_vars={
                    "user_id": "u1",
                    "current_user_text": "当时在 Magi 项目里我住在哪里",
                    "intent": "coding",
                    "memory_context_workspace": "/tmp/magi",
                },
            ),
        )

        assert result.success is True
        request = fake_mq.query.await_args.args[0]
        assert request.time_range == {"as_of": 1234.0}
        assert request.context_scope == {}
        assert request.context_signals.workspace_path == "/tmp/magi"
        assert request.context_signals.user_text == "当时在 Magi 项目里我住在哪里"
        assert request.context_signals.task_category == "coding"

    @pytest.mark.asyncio
    async def test_tool_execution_does_not_treat_fallback_workspace_as_memory_context(
        self,
    ):
        """A tool execution fallback directory is not a trusted chat project."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool
        from magi.memory.hybrid_retrieval.models import RetrievalPayload

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(return_value=RetrievalPayload())
        fake_mq = _make_fake_mq(fake_service)

        result = await MemoryQueryTool().execute(
            {"query": "what did we decide?"},
            _make_context(
                fake_mq=fake_mq,
                workspace="/tmp/fallback-cwd",
                env_vars={"user_id": "u1"},
            ),
        )

        assert result.success is True
        request = fake_mq.query.await_args.args[0]
        assert request.context_signals.workspace_path is None

    @pytest.mark.asyncio
    async def test_tool_execution_passes_explicit_session_when_provided(self):
        """Should preserve an explicitly requested session-local lookup."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[],
                l1_events=[],
                l2_entity_cards=[],
                l2_relationships=[],
                l2_assertions=[],
                l3_reflections=[],
                l4_procedures=[],
                trace={"query_mode": "detail"},
            )
        )
        fake_mq = _make_fake_mq(fake_service)
        tool = MemoryQueryTool()
        context = _make_context(
            fake_mq=fake_mq,
            env_vars={"user_id": "local_user", "session_id": "session-ignored"},
        )

        result = await tool.execute(
            {
                "query": "这一轮我刚刚说了什么",
                "query_mode": "episode_recall",
                "session_id": "session-explicit",
            },
            context,
        )

        assert result.success is True
        request = fake_mq.query.await_args.args[0]
        assert request.session_id == "session-explicit"


    @pytest.mark.asyncio
    async def test_tool_returns_error_when_memory_query_port_unavailable(self):
        """Should return an error result when memory_query capability is not wired."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool
        from magi.tools.schema import ToolExecutionContext

        tool = MemoryQueryTool()
        # context with no capabilities
        context = ToolExecutionContext(agent_id="test")

        result = await tool.execute({"query": "test"}, context)
        assert result.success is False
        assert "memory_query" in result.error
