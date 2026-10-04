"""Unified prompt-cache layer and typed dynamic-context breakpoints."""

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
import pytest
from magi.llm.provider_bridge.cache_policy import (
    last_user_message_index,
    mark_history_breakpoint,
    mark_tool_loop_tail_breakpoint,
    split_on_boundary,
)
from magi.utils.model_context_messages import (
    build_launch_context_message,
    build_runtime_world_state_message,
    build_working_context_message,
    dynamic_context_start_index,
)

STABLE = "STABLE HEAD identity + boundary + tool catalog + persona"
DYNAMIC = "DYNAMIC TAIL memory + time"
SYS = f"{STABLE}\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\n{DYNAMIC}"


def test_split_on_boundary() -> None:
    assert split_on_boundary(SYS) == (STABLE, DYNAMIC)
    assert split_on_boundary("no boundary present") is None


def test_last_user_message_index() -> None:
    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]
    assert last_user_message_index(msgs) == 2
    # tool-loop shape: tool results sit after the human turn but are role "tool"
    loop = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "tool_call_id": "t1", "content": "{}"},
    ]
    assert last_user_message_index(loop) == 0
    assert last_user_message_index([{"role": "assistant", "content": "a"}]) == -1


@pytest.mark.parametrize(
    "builder",
    [
        build_runtime_world_state_message,
        build_working_context_message,
        build_launch_context_message,
    ],
)
def test_each_dynamic_context_kind_starts_the_noncacheable_region(builder):
    dynamic = builder("dynamic canary")
    assert dynamic is not None
    messages = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "answer"},
        dynamic,
        {"role": "user", "content": "current"},
    ]
    assert dynamic_context_start_index(messages) == 2
    assert dynamic_context_start_index(messages[:2]) == -1


@pytest.mark.parametrize(
    "content",
    [
        "plain answer",
        [{"type": "text", "text": "first block"}, {"type": "text", "text": "last block"}],
        [],
    ],
)
@pytest.mark.parametrize("index", [-1, 1, 5])
def test_history_marker_changes_only_the_valid_boundary_last_block(content, index):
    from copy import deepcopy

    original = [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": content},
        {"role": "user", "content": "current context"},
    ]
    before = deepcopy(original)
    expected = deepcopy(original)
    if index == 1 and content:
        blocks = (
            [{"type": "text", "text": content}] if isinstance(content, str) else deepcopy(content)
        )
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
        expected[1]["content"] = blocks
    actual = mark_history_breakpoint(original, index)
    assert actual == expected
    assert original == before


@pytest.mark.parametrize("active", [True, False])
def test_tool_tail_marker_requires_an_active_loop_and_preserves_input(active):
    from copy import deepcopy

    messages = [
        {"role": "user", "content": [{"type": "text", "text": "u1"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}],
        },
    ]
    before = deepcopy(messages)
    expected = deepcopy(messages)
    if active:
        expected[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
    assert mark_tool_loop_tail_breakpoint(messages, active=active) == expected
    assert messages == before
