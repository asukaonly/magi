# backend/tests/memory/hybrid_retrieval/test_indexical_resolver.py
"""Unit tests for indexical_resolver + the ConversationTurn / RetrievalQuery
schema extension."""

from __future__ import annotations

import pytest


def test_conversation_turn_is_frozen_dataclass():
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turn = ConversationTurn(role="user", content="hi", timestamp=1700000000.0)
    assert turn.role == "user"
    assert turn.content == "hi"
    assert turn.timestamp == 1700000000.0
    # Frozen: attempting to reassign raises
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        turn.content = "mutated"  # type: ignore[misc]


def test_retrieval_query_has_optional_conversation_context_field():
    from magi.memory.hybrid_retrieval.models import (
        ConversationTurn,
        RetrievalQuery,
    )
    rq = RetrievalQuery(query="q")
    assert rq.conversation_context is None

    rq2 = RetrievalQuery(
        query="q",
        conversation_context=[
            ConversationTurn(role="user", content="hi", timestamp=1.0)
        ],
    )
    assert rq2.conversation_context is not None
    assert len(rq2.conversation_context) == 1


def test_resolver_detects_cjk_dangshi():
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [
        ConversationTurn(role="user", content="q", timestamp=0.0),
        ConversationTurn(role="assistant", content="a", timestamp=100.0),
    ]
    result = resolve(query="当时我说了什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.cue_matched == "当时"


def test_resolver_detects_cjk_wo_shuo_guo():
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [
        ConversationTurn(role="assistant", content="a", timestamp=100.0),
    ]
    result = resolve(query="我说过我喜欢什么音乐", conversation_context=turns)
    assert result.is_indexical is True
    assert result.cue_matched == "我说过"


def test_resolver_detects_english_just_now():
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [
        ConversationTurn(role="assistant", content="a", timestamp=100.0),
    ]
    result = resolve(
        query="what did I tell you just now",
        conversation_context=turns,
    )
    assert result.is_indexical is True
    assert "just now" in result.cue_matched.lower()


def test_resolver_english_word_boundary_no_false_positive_on_yearlier():
    """Word-boundary regex must not match 'earlier' inside 'earliest'."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [ConversationTurn(role="assistant", content="a", timestamp=100.0)]
    result = resolve(query="what's the earliest sunrise time", conversation_context=turns)
    assert result.is_indexical is False  # 'earliest' is not 'earlier'


def test_resolver_no_cue_returns_not_indexical():
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [ConversationTurn(role="assistant", content="a", timestamp=100.0)]
    result = resolve(query="what's the weather like", conversation_context=turns)
    assert result.is_indexical is False
    assert result.cue_matched is None


def test_resolver_cue_but_empty_context_logs_orphan():
    """Cue without context: don't override (no anchor possible), but record
    the cue for telemetry."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    result = resolve(query="当时我说什么", conversation_context=None)
    assert result.is_indexical is False
    assert result.cue_matched == "当时"
    assert result.confidence == 0.5
    assert result.temporal_anchor is None


def test_resolver_cue_but_no_assistant_turn_orphans():
    """Cue + context with only user turns → orphan (need assistant to anchor)."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [ConversationTurn(role="user", content="q", timestamp=0.0)]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is False
    assert result.cue_matched == "当时"
    assert result.confidence == 0.5


def test_resolver_anchor_on_most_recent_assistant_turn():
    """When multiple assistant turns exist, anchor on the most recent."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [
        ConversationTurn(role="user", content="q1", timestamp=0.0),
        ConversationTurn(role="assistant", content="a1", timestamp=100.0),
        ConversationTurn(role="user", content="q2", timestamp=200.0),
        ConversationTurn(role="assistant", content="a2", timestamp=300.0),
        ConversationTurn(role="user", content="q3", timestamp=400.0),
    ]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.temporal_anchor == (180.0, 420.0)  # 300 ± 120
