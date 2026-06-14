"""Unified prompt-cache layer: capability gate + boundary split + marker placement (#110)."""

from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.config.models import ModelVendor
from magi.llm.provider_bridge.cache_policy import (
    cache_marked_system_content,
    split_on_boundary,
    vendor_supports_cache_marker,
)

STABLE = "STABLE HEAD identity + boundary + tool catalog"
DYNAMIC = "DYNAMIC TAIL persona + memory + time"
SYS = f"{STABLE}\n{SYSTEM_PROMPT_CACHE_BOUNDARY}\n{DYNAMIC}"


def test_vendor_capability_gate() -> None:
    # Providers whose wire API honors inline cache_control markers.
    assert vendor_supports_cache_marker(ModelVendor.ANTHROPIC)
    assert vendor_supports_cache_marker(ModelVendor.DASHSCOPE)
    # Automatic-only providers must NOT get markers (could be ignored or 400).
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


def test_unsupported_provider_returns_plain_str_without_sentinel() -> None:
    out = cache_marked_system_content(SYS, supports_marker=False)
    assert isinstance(out, str)
    assert SYSTEM_PROMPT_CACHE_BOUNDARY not in out
    assert STABLE in out and DYNAMIC in out


def test_supported_provider_marks_stable_head_only() -> None:
    out = cache_marked_system_content(SYS, supports_marker=True)
    assert isinstance(out, list)
    assert out[0]["type"] == "text"
    assert out[0]["text"] == STABLE
    assert out[0]["cache_control"] == {"type": "ephemeral"}
    assert out[1]["text"] == DYNAMIC
    assert "cache_control" not in out[1]
    assert all(SYSTEM_PROMPT_CACHE_BOUNDARY not in b["text"] for b in out)


def test_supported_provider_no_boundary_is_not_marked() -> None:
    # Without an explicit stable/dynamic boundary we don't guess — marking a
    # possibly-volatile whole-system would just pay cache-write cost with no read.
    out = cache_marked_system_content("plain stable system", supports_marker=True)
    assert out == "plain stable system"
