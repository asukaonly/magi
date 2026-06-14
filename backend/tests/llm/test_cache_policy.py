"""Unified prompt-cache layer: capability gate, boundary split, head-only system
field, and per-turn-context injection into the message stream (#110 / #100)."""

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.config.models import ModelVendor
from magi.llm.provider_bridge.cache_policy import (
    cache_marked_system_content,
    extract_turn_context,
    inject_turn_context,
    split_on_boundary,
    vendor_supports_cache_marker,
)

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


def test_no_boundary_system_unchanged() -> None:
    assert cache_marked_system_content("plain system", supports_marker=True) == "plain system"
    assert cache_marked_system_content("plain system", supports_marker=False) == "plain system"


# --- per-turn tail injection into the message stream ---


def test_extract_turn_context() -> None:
    assert extract_turn_context(SYS) == DYNAMIC
    assert extract_turn_context("no boundary") == ""


def test_inject_prepends_wrapped_tail_to_last_user_message_str() -> None:
    messages = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "current question"},
    ]
    out = inject_turn_context(messages, SYS)

    # original list/dicts untouched
    assert messages[-1]["content"] == "current question"
    # context prepended (wrapped) to the LAST user message, question still last
    last = out[-1]["content"]
    assert last.startswith("<turn_context>")
    assert DYNAMIC in last
    assert last.endswith("current question")
    # earlier messages unchanged -> history stays byte-stable / cacheable
    assert out[0] == messages[0]
    assert out[1] == messages[1]


def test_inject_into_list_content_prepends_text_block() -> None:
    messages = [{"role": "user", "content": [{"type": "image", "source": "x"}]}]
    out = inject_turn_context(messages, SYS)
    blocks = out[0]["content"]
    assert blocks[0]["type"] == "text" and DYNAMIC in blocks[0]["text"]
    assert blocks[1] == {"type": "image", "source": "x"}


def test_inject_no_boundary_returns_messages_unchanged() -> None:
    messages = [{"role": "user", "content": "hi"}]
    assert inject_turn_context(messages, "no boundary system") is messages


def test_inject_no_user_message_appends_context_turn() -> None:
    messages = [{"role": "assistant", "content": "hello"}]
    out = inject_turn_context(messages, SYS)
    assert out[-1]["role"] == "user"
    assert DYNAMIC in out[-1]["content"]
