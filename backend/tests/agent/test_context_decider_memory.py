"""Tests for ContextDecider memory retrieval guidance."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

from magi.tools.context_decider_context import ContextDeciderContext


class TestContextDeciderMemoryGuidance:
    """Tests for memory retrieval guidance in ContextDecider."""

    def test_evaluate_memory_need_time_based_query(self):
        """Should detect memory retrieval need for time-based queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What did I browse yesterday?",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert guidance.recommended is True

    def test_evaluate_memory_need_browsing_pattern(self):
        """Should detect memory retrieval for browsing pattern queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "Analyze my browsing patterns this week",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert guidance.recommended is True

    def test_evaluate_memory_need_no_need(self):
        """Should not trigger for queries that don't need memory."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What is the weather in Tokyo?",
            {}
        )

        # Weather query doesn't need personal memory
        assert guidance is None

    @pytest.mark.asyncio
    async def test_decide_adds_memory_query_for_historical_questions(self):
        """Should expose memory_query even when the fast model omits it."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"history question",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "What did I browse yesterday?",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" in decision.tools
        assert decision.memory_route == "explicit_query"
        assert decision.routing_memory_hint == {
            "query": "What did I browse yesterday?",
            "query_mode": "episode_recall",
            "sources": ["timeline"],
            "time_range": {"relative": "1d"},
        }

    @pytest.mark.asyncio
    async def test_decide_does_not_route_workflow_reuse_to_memory_query(self):
        """Workflow reuse should stay in implicit context, not explicit memory query."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"code_execution","tools":[],"deep_thinking":false,"reasoning":"workflow reuse",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "按之前那套流程修一下这个 bug",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" not in decision.tools
        assert decision.memory_route == "none"
        assert decision.routing_memory_hint is None

    @pytest.mark.asyncio
    async def test_decide_keeps_memory_route_none_when_memory_query_tool_is_unavailable(self):
        """Historical queries should not claim explicit recall when the tool is unavailable."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "web_search", "description": "Search the web", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["web_search"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"history question",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "What did I browse yesterday?",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" not in decision.tools
        assert decision.memory_route == "none"
        assert decision.routing_memory_hint is None

    @pytest.mark.asyncio
    async def test_decide_routes_preference_recall_to_memory_query(self):
        """Preference recall should promote memory_query with recall intent."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"preference question",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "我喜欢什么天气",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" in decision.tools
        assert decision.memory_route == "explicit_query"
        assert decision.routing_memory_hint == {
            "query": "我喜欢什么天气",
            "query_mode": "exact_fact",
            "sources": ["profile", "chat"],
        }

    @pytest.mark.asyncio
    async def test_decide_routes_profile_fact_recall_to_memory_query(self):
        """Profile-fact recall should promote memory_query with profile-biased sources."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"profile question",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "我的默认工作目录是什么",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" in decision.tools
        assert decision.memory_route == "explicit_query"
        assert decision.routing_memory_hint == {
            "query": "我的默认工作目录是什么",
            "query_mode": "exact_fact",
            "sources": ["profile", "settings"],
        }

    @pytest.mark.asyncio
    async def test_decide_routes_relationship_recall_to_memory_query(self):
        """Relationship recall should promote memory_query with relationship intent."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":[],"deep_thinking":false,"reasoning":"relationship question",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "你记得我们之前约定了什么",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert "memory_query" in decision.tools
        assert decision.memory_route == "explicit_query"
        assert decision.routing_memory_hint == {
            "query": "你记得我们之前约定了什么",
            "query_mode": "exact_fact",
            "sources": ["chat", "relationship"],
        }

    @pytest.mark.asyncio
    async def test_decide_routes_photo_asset_recall_to_memory_query(self):
        """Photo or asset recall should promote explicit memory-query routing."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        tool_registry.get_all_tools_info.return_value = [
            {"name": "memory_query", "description": "Retrieve historical event memory", "type": "tool"},
            {"name": "photo_library_resolve_photo_refs", "description": "Resolve recalled photo assets to local file paths", "type": "tool"},
        ]
        tool_registry.list_tools.return_value = ["memory_query", "photo_library_resolve_photo_refs"]
        tool_registry.is_skill.return_value = False

        llm_adapter = MagicMock()
        llm_adapter.model_name = "dummy-model"
        decider = ContextDecider(tool_registry, llm_adapter)

        async def _fake_chat_response(**kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return SimpleNamespace(
                content=(
                    '{"intent":"chat","tools":["memory_query"],"deep_thinking":false,"reasoning":"photo recall",'
                    '"orchestration_strategy":{"mode":"direct","planner":"task_agent","default_leaf_type":"general-purpose","allow_parallel":false}}'
                ),
                metadata={},
            )

        decider.provider_bridge.chat_response = _fake_chat_response  # type: ignore[method-assign]

        decision = await decider.decide(
            "2022年9月我在哪里拍了照片",
            ContextDeciderContext(
                current_datetime="2024-01-15T10:00:00+08:00",
                timezone="Asia/Shanghai",
            ),
        )

        assert decision.tools == ["memory_query"]
        assert decision.memory_route == "explicit_query"
        assert decision.routing_memory_hint == {
            "query": "2022年9月我在哪里拍了照片",
            "query_mode": "episode_recall",
            "sources": ["timeline"],
        }
