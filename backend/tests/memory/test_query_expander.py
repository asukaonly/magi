"""Tests for query expander."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval import query_expander as query_expander_module
from magi.memory.hybrid_retrieval.query_expander import (
    QueryExpander,
    _drop_cross_script_expansions,
    _has_cjk,
)


class _MockBridge:
    """Minimal mock for LLM provider bridge."""

    def __init__(self, response: str):
        self._response = response

    async def chat(self, **kwargs):
        return self._response


class _FailingBridge:
    async def chat(self, **kwargs):
        raise RuntimeError("LLM unavailable")


@pytest.mark.asyncio
async def test_expand_returns_reformulations():
    bridge = _MockBridge('["what food do I enjoy", "which dishes do I prefer"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("what food do I like")
    assert len(result) == 2
    assert "what food do I enjoy" in result
    assert "which dishes do I prefer" in result


@pytest.mark.asyncio
async def test_expand_strips_whitespace():
    bridge = _MockBridge('[" padded query ", "  another  "]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == ["padded query", "another"]


@pytest.mark.asyncio
async def test_expand_caps_at_two():
    bridge = _MockBridge('["a", "b", "c", "d"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_expand_respects_configured_max_expansions():
    bridge = _MockBridge('["a", "b", "c", "d"]')
    expander = QueryExpander(bridge, max_expansions=3)
    result = await expander.expand("test")
    assert result == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_expand_handles_no_bridge():
    expander = QueryExpander(None)
    result = await expander.expand("test")
    assert result == []


@pytest.mark.asyncio
async def test_expand_handles_llm_failure():
    bridge = _FailingBridge()
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == []


@pytest.mark.asyncio
async def test_expand_handles_invalid_json():
    bridge = _MockBridge("This is not JSON at all")
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == []


def test_invalid_response_log_omits_content_when_full_logging_is_disabled(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        query_expander_module,
        "full_content_logging_enabled",
        lambda: False,
    )

    with caplog.at_level("WARNING", logger=query_expander_module.logger.name):
        result = QueryExpander._parse("QUERY-EXPANSION-CONTENT-CANARY")

    assert result == []
    assert "QUERY-EXPANSION-CONTENT-CANARY" not in caplog.text
    assert "content omitted" in caplog.text


@pytest.mark.asyncio
async def test_expand_handles_json_with_surrounding_text():
    bridge = _MockBridge('Here are the queries: ["query one", "query two"] hope this helps!')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_expand_filters_empty_strings():
    bridge = _MockBridge('["good query", "", "  ", "another good"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == ["good query", "another good"]


# ---------- script-class same-language guard ----------


def test_has_cjk_detects_chinese() -> None:
    assert _has_cjk("猫熬我")
    assert _has_cjk("mixed 中文 and English")


def test_has_cjk_detects_japanese() -> None:
    assert _has_cjk("会議")        # kanji
    assert _has_cjk("ひらがな")     # hiragana
    assert _has_cjk("カタカナ")     # katakana


def test_has_cjk_detects_korean() -> None:
    assert _has_cjk("안녕하세요")


def test_has_cjk_false_for_pure_latin() -> None:
    assert not _has_cjk("hello world")
    assert not _has_cjk("café résumé")  # Latin diacritics, still not CJK
    assert not _has_cjk("")


def test_drop_cross_script_drops_english_when_query_chinese() -> None:
    """Real bug we hit: CJK query, LLM expanded to English. Indexed
    content is CJK, English keywords never match. Drop them."""
    kept = _drop_cross_script_expansions(
        "我刚刚在一个群里看到有个图是说猫什么的",
        ["cat wake up photo", "funny cat sleeping picture", "猫 叫醒 图"],
    )
    assert kept == ["猫 叫醒 图"]


def test_drop_cross_script_keeps_mixed_script_expansion() -> None:
    """Don't be too aggressive — code/product names like 'claude 截图'
    are LEGITIMATE mixed expansions. Only fully-translated ones go."""
    kept = _drop_cross_script_expansions(
        "我在 claude 里看到截图功能",
        ["claude 截图 ocr", "screenshot feature in app"],
    )
    # First kept (has CJK so matches), second dropped (pure Latin).
    assert kept == ["claude 截图 ocr"]


def test_drop_cross_script_symmetric_for_english_query() -> None:
    """English-origin query expanded into Chinese is also wrong —
    the user's English memories aren't indexed under Chinese tokens."""
    kept = _drop_cross_script_expansions(
        "what was the meeting about",
        ["meeting agenda decisions", "会议议程", "team standup notes"],
    )
    assert "会议议程" not in kept
    assert "meeting agenda decisions" in kept
    assert "team standup notes" in kept


def test_drop_cross_script_handles_empty_input() -> None:
    assert _drop_cross_script_expansions("anything", []) == []


@pytest.mark.asyncio
async def test_expand_filters_cross_script_end_to_end() -> None:
    """End-to-end: CJK query + English LLM response → empty result.

    Matches the exact failure mode observed in production: the LLM
    translated despite the prompt rule; the post-process filter
    rescues us by dropping translated expansions."""
    bridge = _MockBridge('["cat wake up photo", "funny cat sleeping picture"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("刚刚群里那只猫的梗")
    assert result == []  # Both English expansions dropped.
