from __future__ import annotations

from magi.skills.schema import SkillMetadata
from magi.tools.builtin.weather_tool import WeatherTool
from magi.tools.discovery_index import ToolDiscoveryIndex
from magi.tools.registry import ToolRegistry


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
