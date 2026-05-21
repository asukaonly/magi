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
    """When multiple assistant turns exist, anchor on the most recent.

    Uses realistic unix-second timestamps (post-2001-09-09); the bogus
    timestamp guard in ``_extract_anchor_from_context`` requires this.
    """
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    base = 1_700_000_000.0  # 2023-11-14
    turns = [
        ConversationTurn(role="user", content="q1", timestamp=base + 0),
        ConversationTurn(role="assistant", content="a1", timestamp=base + 100),
        ConversationTurn(role="user", content="q2", timestamp=base + 200),
        ConversationTurn(role="assistant", content="a2", timestamp=base + 300),
        ConversationTurn(role="user", content="q3", timestamp=base + 400),
    ]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    # Most-recent assistant turn is at base + 300, window is ±120s
    assert result.temporal_anchor == (base + 180, base + 420)


def test_resolver_drops_anchor_for_bogus_epoch_timestamps():
    """Defensive guard: when upstream forgets to thread real timestamps in
    and turns default to epoch-zero, the resolver MUST refuse to anchor —
    a ``(-120, +120)`` window centered on epoch would prune every real L1
    event. ``is_indexical`` still fires (the routing intent is valid) but
    ``temporal_anchor`` is dropped so the downstream service falls back
    to the request's existing ``time_range`` (typically None)."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [
        ConversationTurn(role="user", content="q", timestamp=0.0),
        ConversationTurn(role="assistant", content="a", timestamp=0.0),
        ConversationTurn(role="user", content="当时我说什么", timestamp=0.0),
    ]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.force_mode == "episode_recall"
    assert result.l1_retrieval_scope == "conversation_only"
    # No bogus epoch anchor — downstream must not apply a time_range filter.
    assert result.temporal_anchor is None
    # Confidence is lower to surface the degraded mode in traces.
    assert result.confidence == 0.85


def test_resolver_realistic_timestamps_produce_anchor():
    """Regression guard for the real-timestamps contract: when conversation
    context carries realistic unix-second timestamps (post-2001-09-09), the
    resolver must produce a window centered on the most recent assistant
    turn."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    t_real = 1_700_000_100.0
    turns = [
        ConversationTurn(role="user", content="q", timestamp=t_real - 30),
        ConversationTurn(role="assistant", content="a", timestamp=t_real),
        ConversationTurn(role="user", content="当时我说什么", timestamp=t_real + 60),
    ]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.temporal_anchor == (t_real - 120.0, t_real + 120.0)
    assert result.confidence == 0.95
