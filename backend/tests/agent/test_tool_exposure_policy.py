from __future__ import annotations

from types import SimpleNamespace

from magi.agent.task_agents.handlers.tool_exposure_policy import ToolExposurePolicy


class _Tool:
    def __init__(self, name: str, effect_class: str) -> None:
        self._schema = SimpleNamespace(
            name=name,
            effect_class=effect_class,
            effect_replay_policy=(
                "read_only" if effect_class == "read_only" else "reconcilable"
            ),
            dangerous=effect_class == "destructive",
            requires_auth=False,
            metadata={},
        )

    def get_schema(self) -> SimpleNamespace:
        return self._schema


class _Registry:
    def __init__(self, effects: dict[str, str]) -> None:
        self._tools = {name: _Tool(name, effect) for name, effect in effects.items()}

    def get_tool(self, name: str) -> _Tool | None:
        return self._tools.get(name)


def test_tool_exposure_policy_reuses_recent_read_only_superset() -> None:
    now = 1000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"weather", "web-search", "find-relevant-tools"}
    registry = _Registry({name: "read_only" for name in registered})

    first = policy.resolve(
        session_key="chat:s1",
        requested_tools=["weather", "web-search", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )
    assert first == ["weather", "web-search", "find-relevant-tools"]

    now = 1060.0
    second = policy.resolve(
        session_key="chat:s1",
        requested_tools=["weather"],
        registered_tools=registered,
        tool_registry=registry,
    )

    assert second == ["weather", "web-search", "find-relevant-tools"]


def test_tool_exposure_policy_does_not_reuse_write_tool_as_an_extra() -> None:
    now = 2000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"file_read", "file_write", "find-relevant-tools"}
    registry = _Registry(
        {
            "file_read": "read_only",
            "file_write": "local_write",
            "find-relevant-tools": "read_only",
        }
    )

    policy.resolve(
        session_key="chat:s2",
        requested_tools=["file_read", "file_write", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )

    now = 2060.0
    read_only = policy.resolve(
        session_key="chat:s2",
        requested_tools=["file_read", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )

    assert read_only == ["file_read", "find-relevant-tools"]


def test_tool_exposure_policy_never_reuses_unknown_effect_as_an_extra() -> None:
    now = 2500.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"bash", "weather", "find-relevant-tools"}
    registry = _Registry(
        {
            "bash": "unknown",
            "weather": "read_only",
            "find-relevant-tools": "read_only",
        }
    )
    policy.resolve(
        session_key="chat:s-agent",
        requested_tools=["bash", "weather", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )

    now = 2560.0
    resolved = policy.resolve(
        session_key="chat:s-agent",
        requested_tools=["weather", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )

    assert resolved == ["weather", "find-relevant-tools"]


def test_tool_exposure_policy_expires_cached_superset() -> None:
    now = 3000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=30.0, clock=clock)
    registered = {"weather", "web-search", "find-relevant-tools"}
    registry = _Registry({name: "read_only" for name in registered})

    policy.resolve(
        session_key="chat:s3",
        requested_tools=["weather", "web-search", "find-relevant-tools"],
        registered_tools=registered,
        tool_registry=registry,
    )

    now = 3045.0
    resolved = policy.resolve(
        session_key="chat:s3",
        requested_tools=["weather"],
        registered_tools=registered,
        tool_registry=registry,
    )

    assert resolved == ["weather"]


def test_tool_exposure_policy_preserves_current_tools_when_registry_is_empty() -> None:
    policy = ToolExposurePolicy()

    resolved = policy.resolve(
        session_key="chat:s4",
        requested_tools=["memory_query"],
        registered_tools=set(),
        tool_registry=None,
    )

    assert resolved == ["memory_query"]
