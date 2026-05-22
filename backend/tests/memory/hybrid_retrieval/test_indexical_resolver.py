# backend/tests/memory/hybrid_retrieval/test_indexical_resolver.py
"""Unit tests for indexical_resolver + the ConversationTurn / RetrievalQuery
schema extension.

Phase 3 design correction (2026-05-22): the resolver no longer extracts a
temporal_anchor. '当时/那时/上次' in Chinese typically references deep
historical context (days/weeks/months ago), not the immediate prior turn
±2min. The resolver now produces pure routing overrides
(force episode_recall + l1_retrieval_scope=conversation_only); L1 content
matching (BM25 + vector) does the actual event finding.
"""

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
    """Cue without ANY context: don't override (intent too weak to ground),
    but record the cue for telemetry."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    result = resolve(query="当时我说什么", conversation_context=None)
    assert result.is_indexical is False
    assert result.cue_matched == "当时"
    assert result.confidence == 0.5


def test_resolver_cue_plus_user_only_context_still_fires():
    """Phase 3 design correction: with the temporal_anchor extraction
    removed, an assistant turn is no longer required to ground the
    indexical reference. ANY conversation context is enough to confirm
    the user is doing a follow-up (vs. accidentally hitting cue words
    at session start). The routing override fires regardless of role
    distribution."""
    from magi.memory.hybrid_retrieval.indexical_resolver import resolve
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    turns = [ConversationTurn(role="user", content="q", timestamp=0.0)]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.cue_matched == "当时"
    assert result.force_mode == "episode_recall"
    assert result.l1_retrieval_scope == "conversation_only"


def test_resolver_never_produces_temporal_anchor():
    """Phase 3 design correction: '当时' typically references deep
    historical context, not the immediate prior turn ±2min. The resolver
    now NEVER produces a temporal_anchor — Phase 3 is pure routing
    override (force L1 conversation_only + episode_recall mode). L1
    content matching does the actual finding."""
    from magi.memory.hybrid_retrieval.indexical_resolver import (
        IndexicalResolution,
        resolve,
    )
    from magi.memory.hybrid_retrieval.models import ConversationTurn

    # Even with realistic timestamps the resolver doesn't anchor:
    turns = [
        ConversationTurn(role="user", content="q", timestamp=1700000000.0),
        ConversationTurn(role="assistant", content="a", timestamp=1700000100.0),
    ]
    result = resolve(query="当时我说什么", conversation_context=turns)
    assert result.is_indexical is True
    assert result.force_mode == "episode_recall"
    assert result.l1_retrieval_scope == "conversation_only"
    # Field removed from the dataclass entirely.
    assert not hasattr(result, "temporal_anchor"), (
        "Phase 3 design correction: temporal_anchor field removed from "
        f"IndexicalResolution; got attribute on {result!r}"
    )
    # Defensive: the type itself should not declare the field either.
    assert "temporal_anchor" not in IndexicalResolution.__dataclass_fields__
