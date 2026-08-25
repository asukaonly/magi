"""Unified prompt-cache layer: capability gate, boundary split, head-only system
field, and per-turn-context injection into the message stream (#110 / #100)."""

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.config.models import ModelVendor
from magi.llm.provider_bridge.cache_policy import (
    cache_marked_system_content,
    last_user_message_index,
    mark_history_breakpoint,
    mark_tool_loop_tail_breakpoint,
    split_on_boundary,
    turn_context_message_index,
    vendor_supports_cache_marker,
)

EPHEMERAL = {"type": "ephemeral"}

STABLE = "STABLE HEAD identity + boundary + tool catalog + persona"
DYNAMIC = "DYNAMIC TAIL memory + time"
SYS = f"{STABLE}\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\n{DYNAMIC}"


def test_vendor_capability_gate() -> None:
    assert vendor_supports_cache_marker(ModelVendor.ANTHROPIC)
    assert vendor_supports_cache_marker(ModelVendor.DASHSCOPE)
    for v in (
        ModelVendor.OPENAI,
        ModelVendor.DEEPSEEK,
        ModelVendor.GLM,
        ModelVendor.GROK,
        ModelVendor.GEMINI,
        ModelVendor.KIMI,
        ModelVendor.GENERIC,
    ):
        assert not vendor_supports_cache_marker(v)


def test_split_on_boundary() -> None:
    assert split_on_boundary(SYS) == (STABLE, DYNAMIC)
    assert split_on_boundary("no boundary present") is None


# --- system field is HEAD-ONLY; the tail moves to the message stream (P2a) ---


def test_unsupported_provider_system_is_head_only() -> None:
    out = cache_marked_system_content(SYS, supports_marker=False)
    assert out == STABLE  # head only, tail dropped from system, no sentinel


def test_supported_provider_marks_head_only_no_tail_block() -> None:
    out = cache_marked_system_content(SYS, supports_marker=True)
    assert out == [{"type": "text", "text": STABLE, "cache_control": {"type": "ephemeral"}}]


def test_system_head_accepts_1h_ttl() -> None:
    out = cache_marked_system_content(SYS, supports_marker=True, ttl="1h")
    assert out == [
        {"type": "text", "text": STABLE, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]


def test_system_head_default_ttl_omits_field() -> None:
    out = cache_marked_system_content(SYS, supports_marker=True, ttl=None)
    assert out[0]["cache_control"] == {"type": "ephemeral"}  # no ttl key -> 5m default


def test_no_boundary_system_unchanged() -> None:
    assert cache_marked_system_content("plain system", supports_marker=True) == "plain system"
    assert cache_marked_system_content("plain system", supports_marker=False) == "plain system"


# --- cache_whole: stable auxiliary-call system prompts (routing, memory) ---


def test_cache_whole_marks_entire_system_when_no_boundary() -> None:
    # Aux calls (routing/memory) have a stable system but no boundary; cache_whole
    # marks the whole thing for marker vendors so it caches like the main head.
    out = cache_marked_system_content("STABLE ROUTING PROMPT", supports_marker=True, cache_whole=True)
    assert out == [
        {"type": "text", "text": "STABLE ROUTING PROMPT", "cache_control": {"type": "ephemeral"}}
    ]


def test_cache_whole_respects_ttl() -> None:
    out = cache_marked_system_content("S", supports_marker=True, cache_whole=True, ttl="1h")
    assert out == [{"type": "text", "text": "S", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]


def test_cache_whole_noop_for_non_marker_vendor() -> None:
    assert cache_marked_system_content("S", supports_marker=False, cache_whole=True) == "S"


def test_cache_whole_with_boundary_still_splits_head_only() -> None:
    # Boundary takes precedence — never mark a per-turn tail even if cache_whole.
    out = cache_marked_system_content(SYS, supports_marker=True, cache_whole=True)
    assert out == [{"type": "text", "text": STABLE, "cache_control": {"type": "ephemeral"}}]


def test_cache_whole_off_leaves_plain_system() -> None:
    assert cache_marked_system_content("S", supports_marker=True, cache_whole=False) == "S"


# --- rolling history cache breakpoint (Anthropic) ---


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


def test_turn_context_message_index() -> None:
    messages = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "<turn_context>\ndynamic\n</turn_context>"},
        {"role": "user", "content": "current"},
    ]
    assert turn_context_message_index(messages) == 2
    assert turn_context_message_index(messages[:2]) == -1


def test_mark_history_breakpoint_marks_last_block_of_boundary_message() -> None:
    api = [
        {"role": "user", "content": [{"type": "text", "text": "u1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a1"}]},
        {"role": "user", "content": [{"type": "text", "text": "ctx+u2"}]},
    ]
    out = mark_history_breakpoint(api, 1)
    # boundary message gets the breakpoint on its last block
    assert out[1]["content"][-1]["cache_control"] == EPHEMERAL
    # current turn (carries turn_context) stays unmarked -> reusable next turn
    assert "cache_control" not in out[2]["content"][-1]
    # earlier history untouched
    assert "cache_control" not in out[0]["content"][-1]
    # input not mutated
    assert "cache_control" not in api[1]["content"][-1]


def test_mark_history_breakpoint_promotes_string_content_to_block() -> None:
    api = [{"role": "assistant", "content": "plain answer"}]
    out = mark_history_breakpoint(api, 0)
    assert out[0]["content"] == [
        {"type": "text", "text": "plain answer", "cache_control": EPHEMERAL}
    ]


def test_mark_history_breakpoint_noop_for_out_of_range_index() -> None:
    api = [{"role": "user", "content": "u1"}]
    assert mark_history_breakpoint(api, -1) == api
    assert mark_history_breakpoint(api, 5) == api
    # nothing marked
    assert "cache_control" not in str(api)


# --- tool-loop tail breakpoint (Anthropic) ---


def test_mark_tool_loop_tail_marks_last_message_when_active() -> None:
    api = [
        {"role": "user", "content": [{"type": "text", "text": "u1"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]},
    ]
    out = mark_tool_loop_tail_breakpoint(api, active=True)
    # the growing tool-result tail caches for the next loop iteration
    assert out[-1]["content"][-1]["cache_control"] == EPHEMERAL
    # earlier messages untouched; input not mutated
    assert "cache_control" not in str(api)


def test_mark_tool_loop_tail_noop_when_inactive() -> None:
    # simple turn: last message holds volatile per-turn context -> marking it
    # would only waste a cache write, so the tail breakpoint must stay off.
    api = [{"role": "user", "content": [{"type": "text", "text": "ctx+q"}]}]
    assert mark_tool_loop_tail_breakpoint(api, active=False) == api
    assert "cache_control" not in str(api)
