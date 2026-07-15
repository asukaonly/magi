"""Unit tests for MemoryQueryTool."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from magi_plugin_sdk.capabilities import ToolCapabilities


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

    caps = ToolCapabilities(memory_query=fake_mq)
    return ToolExecutionContext(agent_id="test", capabilities=caps, **kwargs)


class TestMemoryQueryTool:
    """Tests for MemoryQueryTool."""

    def test_tool_initializes_schema(self):
        """Should allow schema initialization."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()

        assert tool.get_schema().name == "memory_query"

    def test_tool_schema_definition(self):
        """Should have proper schema definition."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        assert schema.name == "memory_query"
        assert "memory" in schema.category.lower()
        assert len(schema.parameters) >= 2

    def test_tool_parameters(self):
        """Should require both query and query_mode."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        param_names = [p.name for p in schema.parameters]
        assert "query" in param_names
        assert "time_range" in param_names
        assert "context_scope" in param_names
        # `sources` was deliberately removed — the LLM has no reliable
        # mapping from natural language to concrete source identifiers
        # and the resulting filter was a post-rank exclude that threw
        # away real hits. Source narrowing now lives only on the
        # internal RetrievalQuery API. See memory_query_tool.py for the
        # full rationale.
        assert "sources" not in param_names
        assert "query_mode" in param_names

        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True
        query_mode_param = next(p for p in schema.parameters if p.name == "query_mode")
        # query_mode is optional — the engine auto-detects the mode from
        # query text; LLM only passes one when explicitly overriding.
        # The spec's description says so; the assertion below was a
        # latent stale test (it never fired previously because an
        # earlier assertion on the now-removed `sources` param failed
        # first).
        assert query_mode_param.required is False
        assert query_mode_param.enum is not None
        assert "exact_fact" in query_mode_param.enum
        assert "experience_recall" in query_mode_param.enum
        time_range_param = next(p for p in schema.parameters if p.name == "time_range")
        assert time_range_param.required is False
        assert "as_of" in time_range_param.description
        assert "user preferences" in schema.description
        assert "personal facts" in schema.description
        assert "customized settings" in schema.description

    def test_summary_categories_description_lists_only_registered_categories(self):
        """Should never advertise summary categories that no plugin actually registers."""
        from magi.tools.builtin.memory_query_tool import _build_summary_categories_description

        class _Profile:
            def __init__(self, summary_category: str) -> None:
                self.summary_category = summary_category

        class _PluginProjectionService:
            def iter_merged_summary_profiles(self) -> list[_Profile]:
                return [_Profile("browser_activity")]

        description = _build_summary_categories_description(_PluginProjectionService())

        assert "browser_activity" in description
        # The ghost categories from the previous static fallback must not leak
        # into the tool schema once the plugin manager is bound.
        assert "media_listening" not in description
        assert "coding_activity" not in description

    def test_summary_categories_description_when_no_plugin_registers(self):
        """Should tell the model to omit the field instead of listing fake categories."""
        from magi.tools.builtin.memory_query_tool import _build_summary_categories_description

        class _EmptyProjectionService:
            def iter_merged_summary_profiles(self) -> list[object]:
                return []

        for projection_service in (None, _EmptyProjectionService()):
            description = _build_summary_categories_description(projection_service)
            assert "Omit this field" in description
            # No invented categories may appear when none are actually registered.
            assert "browser_activity" not in description
            assert "media_listening" not in description
            assert "coding_activity" not in description

    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Should execute query and return projected recall plus debug payloads."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        fake_service = MagicMock(name="retrieval_service")
        fake_service.query = AsyncMock(
            return_value=MagicMock(
                l0_workbench=[{"summary": "Current goal"}],
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
        tool = MemoryQueryTool()
        context = _make_context(fake_mq=fake_mq, task_id="test-task")

        result = await tool.execute({"query": "test query", "query_mode": "exact_fact"}, context)

        assert result.success is True
        assert result.data["historical_recall"]["summary"] == "你讨厌潮湿天气。"
        assert (
            result.data["historical_recall"]["findings"][0]["statement"]
            == "user:local_user DISLIKES weather_state:humid"
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
    async def test_tool_execution_passes_scope_and_as_of_time(self):
        """Resolved condition scope and point-in-time intent must reach retrieval."""
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
                "context_scope": {"project": "magi", "activity": "coding"},
            },
            _make_context(fake_mq=fake_mq, env_vars={"user_id": "u1"}),
        )

        assert result.success is True
        request = fake_mq.query.await_args.args[0]
        assert request.time_range == {"as_of": 1234.0}
        assert request.context_scope == {"project": "magi", "activity": "coding"}

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
    async def test_tool_to_claude_format(self):
        """Should export to Claude tool format."""
        from magi.tools.builtin.memory_query_tool import MemoryQueryTool

        tool = MemoryQueryTool()
        claude_format = tool.to_claude_format()

        assert claude_format["name"] == "memory_query"
        assert "input_schema" in claude_format
        properties = claude_format["input_schema"]["properties"]
        # `sources` is intentionally NOT exposed to the LLM — see the
        # block-comment in memory_query_tool.py for why.
        assert "sources" not in properties
        # Sanity-check that legitimate params are still there.
        assert "query" in properties
        assert "time_range" in properties
        assert "context_scope" in properties
        assert "query_mode" in properties

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
