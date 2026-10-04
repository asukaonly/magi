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
