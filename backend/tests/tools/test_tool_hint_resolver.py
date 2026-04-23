from __future__ import annotations

from magi.tools.builtin.bash_tool import BashTool
from magi.tools.builtin.file_edit_tool import FileEditTool
from magi.tools.builtin.file_read_tool import FileReadTool
from magi.tools.builtin.file_write_tool import FileWriteTool
from magi.tools.builtin.glob_tool import GlobTool
from magi.tools.builtin.grep_tool import GrepTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.recommender import ToolRecommender
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext
from magi.tools.tool_hint_resolver import ToolHintResolver


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_class in (
        GlobTool,
        GrepTool,
        FileReadTool,
        FileEditTool,
        FileWriteTool,
        BashTool,
        WebSearchTool,
        WebFetchTool,
    ):
        registry.register(tool_class)
    return registry


def test_tool_hint_resolver_ranks_file_tools_for_anchor_search() -> None:
    registry = _build_registry()
    resolver = ToolHintResolver(registry)

    hint = resolver.resolve(
        user_message="分析 backend/src/magi/agent 的调用链路",
        available_tools=["glob", "grep", "file_read"],
        scope_hints=["The request references an explicit path or subdirectory."],
    )

    assert hint["task_intent"] == "trace_implementation"
    assert hint["domain"] == "codebase"
    assert hint["operation"] == "discover"
    assert hint["tool_hints"][0]["tool"] in {"glob", "grep"}
    assert any(item["tool"] == "file_read" for item in hint["tool_hints"])


def test_tool_hint_resolver_prefers_fetch_for_detail_requests() -> None:
    registry = _build_registry()
    resolver = ToolHintResolver(registry)

    hint = resolver.resolve(
        user_message="搜一下最近7天杭州的重要新闻，并展开第3条详情",
        available_tools=["web-search", "web-fetch"],
        request_profile="research",
    )

    assert hint["task_intent"] == "research_external"
    assert hint["domain"] == "web"
    assert hint["operation"] == "fetch"
    assert hint["tool_hints"][0]["tool"] == "web-fetch"
    assert hint["target_locality"] == "web"
    assert hint["preferred_resolution_order"] == "web_first"


def test_tool_hint_resolver_marks_ambiguous_external_reference_for_mixed_research_tools() -> None:
    registry = _build_registry()
    resolver = ToolHintResolver(registry)

    hint = resolver.resolve(
        user_message="详细对比下 Magi 和 AnotherProject 的记忆实现",
        available_tools=["web-search", "web-fetch", "file_read", "ask_user_question"],
        request_profile="research",
    )

    assert hint["target_locality"] == "ambiguous_external_reference"
    assert hint["preferred_resolution_order"] == "ask_or_web_before_external_scan"
    assert hint["requires_clarification"] is True


def test_tool_recommender_uses_task_hint_metadata_to_rank_tools() -> None:
    registry = _build_registry()
    recommender = ToolRecommender(registry)
    context = ToolExecutionContext(agent_id="test-agent", workspace=".", permissions=["authenticated"])

    recommendations = recommender.recommend_tools(
        intent="分析 backend/src/magi/agent 的调用链路",
        context=context,
        top_k=3,
        task_hint={"task_intent": "trace_implementation", "domain": "codebase", "operation": "discover"},
    )

    assert recommendations
    assert recommendations[0]["tool"] in {"glob", "grep"}
    assert recommendations[0]["metadata"]["task_intents"]


def test_tool_hint_resolver_deprioritizes_execution_tools_during_anchor_search() -> None:
    registry = _build_registry()
    resolver = ToolHintResolver(registry)

    hint = resolver.resolve(
        user_message="定位 backend/src/magi/tools 里控制 tool hint 排序的实现",
        available_tools=["glob", "grep", "file_read", "bash", "file_edit", "file_write"],
        scope_hints=["The request references an explicit path or subdirectory."],
    )

    ordered = [item["tool"] for item in hint["tool_hints"]]
    assert ordered[:2] == ["glob", "grep"]
    assert ordered.index("bash") > ordered.index("file_read")
    assert ordered.index("file_edit") > ordered.index("file_read")
    assert ordered.index("file_write") > ordered.index("file_read")