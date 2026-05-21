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
