from __future__ import annotations

from magi.skills.schema import SkillMetadata
from magi.mcp.tool_adapter import build_adapter_class
from magi.tools.schema import (
    ParameterType,
    Tool,
    ToolExecutionContext,
    ToolParameter,
    ToolResult,
    ToolSchema,
)
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.discovery_index import ToolDiscoveryIndex
from magi.tools.registry import ToolRegistry


class ExternalCalendarTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="external-calendar-freebusy",
            description="Find external calendar free busy availability and meetings.",
            category="external",
            tags=["calendar", "availability"],
        )

    async def execute(
        self,
        parameters: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = parameters, context
        return ToolResult(success=True, data={})


class ReadAttachmentProbeTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="read_chat_attachment",
            description=(
                "Read a managed chat attachment from the current session by attachment_id. "
                "Use this for earlier uploaded files, PDFs, text files, and images."
            ),
            category="chat",
            tags=["chat", "attachment", "read"],
            parameters=[
                ToolParameter(
                    name="attachment_id",
                    type=ParameterType.STRING,
                    description="Attachment id from the session attachment references.",
                    required=True,
                ),
            ],
            metadata={
                "task_intents": ["inspect_attachment", "answer_from_uploaded_file"],
                "domains": ["chat", "attachments"],
                "operations": ["read", "inspect"],
            },
        )

    async def execute(
        self,
        parameters: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = parameters, context
        return ToolResult(success=True, data={})


class MemoryQueryProbeTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="memory_query",
            description=(
                "Retrieve structured memory context for prior conversations, remembered user "
                "preferences, historical activities, and personal facts."
            ),
            category="memory",
            tags=["memory", "recall", "history"],
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The user's memory question, passed through in full.",
                    required=True,
                ),
            ],
            metadata={
                "task_intents": ["recall_memory", "answer_from_history"],
                "domains": ["memory", "history"],
                "operations": ["retrieve", "recall"],
            },
        )

    async def execute(
        self,
        parameters: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = parameters, context
        return ToolResult(success=True, data={})


class PhotoResolveProbeTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="photo_library_resolve_photo_refs",
            description=(
                "Resolve photo library image references and prepare selected pictures "
                "for chat attachment delivery."
            ),
            category="external",
            tags=["photo", "image", "picture", "attachment"],
            parameters=[
                ToolParameter(
                    name="asset_ref",
                    type=ParameterType.STRING,
                    description="Reusable photo or image reference from recent chat context.",
                    required=True,
                ),
            ],
        )

    async def execute(
        self,
        parameters: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        _ = parameters, context
        return ToolResult(success=True, data={})


def test_discovery_index_searches_tools_and_skills_together(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WeatherTool)
    registry.register_skill_index(
        {
            "calendar-availability": SkillMetadata(
                name="calendar-availability",
                description="Find calendar availability, free busy slots, meetings, and schedules.",
                directory=tmp_path,
                category="calendar",
                tags=["calendar", "availability", "schedule"],
            )
        }
    )

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="帮我找能看日程空档和会议安排的能力，也可能需要天气",
        limit=4,
    )

    names = [item["name"] for item in results]
    assert "calendar-availability" in names
    assert "weather" in names
    assert {item["type"] for item in results} == {"tool", "skill"}


def test_discovery_index_excludes_current_and_internal_tools(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(WeatherTool)
    registry.register_skill_index(
        {
            "weather-planning": SkillMetadata(
                name="weather-planning",
                description="Plan around weather and forecast constraints.",
                directory=tmp_path,
                category="planning",
                tags=["weather", "forecast"],
            )
        }
    )

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="weather forecast",
        limit=4,
        current_tools=["weather"],
        excluded_names={"weather-planning"},
    )

    assert results == []


def test_discovery_index_covers_external_plugin_mcp_and_skill_sources(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ExternalCalendarTool)
    registry.register(
        build_adapter_class(
            server_id="calendar",
            remote={
                "name": "list_events",
                "description": "List calendar events and meeting availability.",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True},
            },
            manager=None,
            call_timeout_ms=1000,
            override=None,
        )
    )
    registry.register_skill_index(
        {
            "calendar-availability": SkillMetadata(
                name="calendar-availability",
                description="Find calendar availability, free busy slots, meetings, and schedules.",
                directory=tmp_path,
                category="calendar",
                tags=["calendar", "availability", "schedule"],
            )
        }
    )

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="calendar meeting availability",
        limit=8,
    )

    by_name = {item["name"]: item for item in results}
    assert by_name["external-calendar-freebusy"]["source"] == "external"
    assert by_name["mcp__calendar__list_events"]["source"] == "mcp"
    assert by_name["calendar-availability"]["source"] == "skill"


def test_discovery_index_uses_parameter_descriptions_for_attachment_queries() -> None:
    registry = ToolRegistry()
    registry.register(ReadAttachmentProbeTool)

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="读取刚才上传的附件内容",
        limit=2,
    )

    assert [item["name"] for item in results] == ["read_chat_attachment"]


def test_discovery_index_prefers_memory_for_prior_conversation_questions() -> None:
    registry = ToolRegistry()
    registry.register(MemoryQueryProbeTool)
    registry.register(WeatherTool)
    registry.register(ReadAttachmentProbeTool)

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="what did I previously say about humid weather",
        limit=2,
    )

    assert results[0]["name"] == "memory_query"
    assert "weather" in {item["name"] for item in results}


def test_discovery_index_keeps_photo_resolution_ahead_of_generic_chat_attachment() -> None:
    registry = ToolRegistry()
    registry.register(ReadAttachmentProbeTool)
    registry.register(PhotoResolveProbeTool)

    index = ToolDiscoveryIndex.from_registry(registry)
    results = index.search(
        query="find the photo from yesterday and attach it to chat",
        limit=2,
    )

    assert results[0]["name"] == "photo_library_resolve_photo_refs"
