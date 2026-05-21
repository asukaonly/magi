"""Phase 3 north star: indexical query + conversation_context produces
authoritative routing overrides (episode_recall + conversation_only +
temporal anchor), bypassing the LLMIntentDecider chain that would otherwise
send the query to L2 KG."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.indexical_resolver import (
    IndexicalResolution,
    resolve,
)
from magi.memory.hybrid_retrieval.models import ConversationTurn


def test_resolve_indexical_query_with_assistant_anchor():
    """Mirror the original bug scenario: user follow-up '当时我怎么说的'
    + 2-turn context where the assistant just said something about names.
    Resolver must return is_indexical=True with anchor from the assistant turn."""
    T_ASSISTANT = 1700000100.0  # arbitrary unix seconds
    turns = [
        ConversationTurn(role="user", content="你知道我是谁吗",
                         timestamp=T_ASSISTANT - 30),
        ConversationTurn(role="assistant", content="子涵或者哈基米。",
                         timestamp=T_ASSISTANT),
        ConversationTurn(role="user", content="用记忆工具去数据库里看看呢，当时我怎么说的",
                         timestamp=T_ASSISTANT + 60),
    ]

    result = resolve(
        query="用记忆工具去数据库里看看呢，当时我怎么说的",
        conversation_context=turns,
    )

    assert result.is_indexical is True, (
        f"expected indexical detection on '当时'; got {result!r}"
    )
    assert result.force_mode == "episode_recall"
    assert result.l1_retrieval_scope == "conversation_only"
    assert result.temporal_anchor is not None
    start, end = result.temporal_anchor
    # Anchor on the assistant turn ±120s
    assert start == T_ASSISTANT - 120.0
    assert end == T_ASSISTANT + 120.0
    assert result.cue_matched == "当时"
    assert result.confidence >= 0.9
