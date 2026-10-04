"""Query expansion parsing, limits, and script filtering through the public path."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from magi.memory.hybrid_retrieval import query_expander as query_expander_module
from magi.memory.hybrid_retrieval.query_expander import QueryExpander


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,options,expected",
    [
        (
            '["what food do I enjoy","which dishes do I prefer"]',
            {},
            ["what food do I enjoy", "which dishes do I prefer"],
        ),
        ('[" padded query ","  another  "]', {}, ["padded query", "another"]),
        ('["good query","","  ","another good"]', {}, ["good query", "another good"]),
        ('["a","b","c","d"]', {}, ["a", "b"]),
        ('["a","b","c","d"]', {"max_expansions": 3}, ["a", "b", "c"]),
        (
            'Here are the queries: ["query one","query two"] hope this helps!',
            {},
            ["query one", "query two"],
        ),
        ("This is not JSON at all", {}, []),
        ("[]", {}, []),
    ],
    ids=[
        "phrases",
        "whitespace",
        "empty-members",
        "default-cap",
        "configured-cap",
        "prose",
        "invalid",
        "empty",
    ],
)
async def test_query_expansion_parses_exact_queries_and_caps_the_result(
    response, options, expected
):
    bridge = SimpleNamespace(chat=AsyncMock(return_value=response))
    assert await QueryExpander(bridge, **options).expand("what food do I like") == expected
    bridge.chat.assert_awaited_once()
    assert bridge.chat.await_args.kwargs["messages"] == [
        {"role": "user", "content": "what food do I like"}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query,expansions,expected",
    [
        ("我刚刚在群里看到猫的图", ["cat photo", "猫 叫醒 图"], ["猫 叫醒 图"]),
        (
            "mixed 中文 and English",
            ["product 截图 ocr", "screenshot feature"],
            ["product 截图 ocr"],
        ),
        ("会議", ["meeting", "会議 記録"], ["会議 記録"]),
        ("ひらがな", ["writing", "かな ことば"], ["かな ことば"]),
        ("カタカナ", ["word", "カタカナ コトバ"], ["カタカナ コトバ"]),
        ("안녕하세요", ["hello", "한국어 기록"], ["한국어 기록"]),
        ("hello world", ["会议议程", "meeting agenda"], ["meeting agenda"]),
        ("café résumé", ["咖啡 记录", "coffee records"], ["coffee records"]),
        ("刚刚群里那只猫的梗", ["cat wake up photo", "funny cat sleeping picture"], []),
    ],
)
async def test_public_expansion_filters_script_changes_and_preserves_mixed_queries(
    query, expansions, expected
):
    bridge = SimpleNamespace(
        chat=AsyncMock(return_value=json.dumps(expansions, ensure_ascii=False))
    )
    assert await QueryExpander(bridge).expand(query) == expected
    bridge.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_unavailable_expansion_falls_back_after_observing_attempted_call():
    assert await QueryExpander(None).expand("query") == []
    bridge = SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError("Model unavailable")))
    assert await QueryExpander(bridge).expand("query") == []
    bridge.chat.assert_awaited_once()


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
