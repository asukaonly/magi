from __future__ import annotations

from magi.agent.task_agents.handlers.tool_exposure_policy import ToolExposurePolicy


def test_tool_exposure_policy_reuses_recent_superset() -> None:
    now = 1000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"weather", "web-search", "find-relevant-tools"}

    first = policy.resolve(
        session_key="chat:s1",
        requested_tools=["weather", "web-search", "find-relevant-tools"],
        registered_tools=registered,
        may_write=False,
    )
    assert first == ["weather", "web-search", "find-relevant-tools"]

    now = 1060.0
    second = policy.resolve(
        session_key="chat:s1",
        requested_tools=["weather"],
        registered_tools=registered,
        may_write=False,
    )

    assert second == ["weather", "web-search", "find-relevant-tools"]


def test_tool_exposure_policy_does_not_reuse_write_tools_for_read_only_turn() -> None:
    now = 2000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"file_read", "bash", "find-relevant-tools"}

    policy.resolve(
        session_key="chat:s2",
        requested_tools=["file_read", "bash", "find-relevant-tools"],
        registered_tools=registered,
        may_write=True,
    )

    now = 2060.0
    read_only = policy.resolve(
        session_key="chat:s2",
        requested_tools=["file_read", "find-relevant-tools"],
        registered_tools=registered,
        may_write=False,
    )

    assert read_only == ["file_read", "find-relevant-tools"]


def test_tool_exposure_policy_never_reuses_agent_as_an_extra_tool() -> None:
    now = 2500.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=300.0, clock=clock)
    registered = {"agent", "weather", "find-relevant-tools"}
    policy.resolve(
        session_key="chat:s-agent",
        requested_tools=["agent", "weather", "find-relevant-tools"],
        registered_tools=registered,
        may_write=True,
    )

    now = 2560.0
    resolved = policy.resolve(
        session_key="chat:s-agent",
        requested_tools=["weather", "find-relevant-tools"],
        registered_tools=registered,
        may_write=True,
    )

    assert resolved == ["weather", "find-relevant-tools"]


def test_tool_exposure_policy_expires_cached_superset() -> None:
    now = 3000.0

    def clock() -> float:
        return now

    policy = ToolExposurePolicy(ttl_seconds=30.0, clock=clock)
    registered = {"weather", "web-search", "find-relevant-tools"}

    policy.resolve(
        session_key="chat:s3",
        requested_tools=["weather", "web-search", "find-relevant-tools"],
        registered_tools=registered,
        may_write=False,
    )

    now = 3045.0
    resolved = policy.resolve(
        session_key="chat:s3",
        requested_tools=["weather"],
        registered_tools=registered,
        may_write=False,
    )

    assert resolved == ["weather"]


def test_tool_exposure_policy_preserves_current_tools_when_registry_is_empty() -> None:
    policy = ToolExposurePolicy()

    resolved = policy.resolve(
        session_key="chat:s4",
        requested_tools=["memory_query"],
        registered_tools=set(),
        may_write=False,
    )

    assert resolved == ["memory_query"]
