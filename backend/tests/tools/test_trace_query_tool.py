"""Unit tests for TraceQueryTool."""

import pytest


class TestTraceQueryTool:
    """Tests for recent trace inspection."""

    def test_tool_schema_definition(self):
        from magi.tools.builtin.trace_query_tool import TraceQueryTool

        tool = TraceQueryTool()
        schema = tool.get_schema()

        assert schema.name == "trace_query"
        param_names = [param.name for param in schema.parameters]
        assert "query" in param_names
        assert "scope" in param_names
        assert "tool_name" in param_names
        assert "include_arguments" in param_names

    @pytest.mark.asyncio
    async def test_tool_returns_recent_previous_turn_trace(self, monkeypatch):
        import magi.tools.builtin.trace_query_tool as trace_query_module
        from magi.tools.builtin.trace_query_tool import TraceQueryTool
        from magi.tools.schema import ToolExecutionContext

        class _FakeTraceService:
            def get_turn_activity_map(self, *, user_id: str, session_id: str):
                assert user_id == "local_user"
                assert session_id == "session-1"
                return {
                    "turn-older": {"status": "completed"},
                    "turn-prev": {"status": "completed"},
                    "turn-current": {"status": "running"},
                }

            def get_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
                assert turn_id == "turn-prev"
                return {
                    "status": "completed",
                    "summary": {
                        "status": "completed",
                        "headline": "Used photo tools",
                        "duration_seconds": 1.25,
                    },
                    "root": {
                        "id": "root",
                        "kind": "turn",
                        "label": "Turn",
                        "status": "completed",
                        "children": [
                            {
                                "id": "tool-1",
                                "kind": "tool",
                                "label": "photo_library_resolve_photo_refs",
                                "status": "completed",
                                "result_preview": "Resolved 2 photo assets",
                                "error": None,
                                "metadata": {
                                    "tool_name": "photo_library_resolve_photo_refs",
                                    "execution_time": 842,
                                    "arguments": {"asset_ref_ids": ["asset-1", "asset-2"]},
                                    "result_json": {"count": 2},
                                },
                                "children": [],
                            }
                        ],
                    },
                }

        monkeypatch.setattr(trace_query_module, "get_chat_trace_read_service", lambda: _FakeTraceService())

        tool = TraceQueryTool()
        context = ToolExecutionContext(
            agent_id="chat",
            env_vars={"user_id": "local_user", "session_id": "session-1", "turn_id": "turn-current"},
        )

        result = await tool.execute({"query": "刚刚用了什么参数和耗时"}, context)

        assert result.success is True
        assert result.data["trace"]["turn_id"] == "turn-prev"
        assert result.data["tool_calls"][0]["tool_name"] == "photo_library_resolve_photo_refs"
        assert result.data["tool_calls"][0]["arguments"] == {"asset_ref_ids": ["asset-1", "asset-2"]}
        assert "duration_ms=842" in result.data["summary_markdown"]

    @pytest.mark.asyncio
    async def test_tool_filters_named_tool(self, monkeypatch):
        import magi.tools.builtin.trace_query_tool as trace_query_module
        from magi.tools.builtin.trace_query_tool import TraceQueryTool
        from magi.tools.schema import ToolExecutionContext

        class _FakeTraceService:
            def get_turn_activity_map(self, *, user_id: str, session_id: str):
                return {"turn-prev": {"status": "completed"}}

            def get_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str):
                return {
                    "status": "completed",
                    "summary": {"status": "completed", "headline": "Trace"},
                    "root": {
                        "id": "root",
                        "kind": "turn",
                        "label": "Turn",
                        "status": "completed",
                        "children": [
                            {
                                "id": "tool-1",
                                "kind": "tool",
                                "label": "memory_query",
                                "status": "completed",
                                "result_preview": "ok",
                                "error": None,
                                "metadata": {"tool_name": "memory_query", "arguments": {"query": "x"}},
                                "children": [],
                            }
                        ],
                    },
                }

        monkeypatch.setattr(trace_query_module, "get_chat_trace_read_service", lambda: _FakeTraceService())

        tool = TraceQueryTool()
        context = ToolExecutionContext(agent_id="chat", env_vars={"user_id": "local_user", "session_id": "session-1"})

        result = await tool.execute(
            {"query": "memory_query 的参数是什么", "tool_name": "memory_query", "scope": "latest_session_turn"},
            context,
        )

        assert result.success is True
        assert len(result.data["tool_calls"]) == 1
        assert result.data["tool_calls"][0]["tool_name"] == "memory_query"