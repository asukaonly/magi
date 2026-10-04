"""Indexical cues only override routing when prior conversation exists."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.indexical_resolver import resolve
from magi.memory.hybrid_retrieval.models import ConversationTurn


@pytest.mark.parametrize(
    "query,roles,cue,active",
    [
        ("当时我说了什么", ["user", "assistant"], "当时", True),
        ("我说过我喜欢什么音乐", ["assistant"], "我说过", True),
        ("what did I tell you just now", ["assistant"], "just now", True),
        ("What did I tell you JUST NOW?", ["user"], "JUST NOW", True),
        ("当时我说什么", ["user"], "当时", True),
        ("what's the earliest sunrise time", ["assistant"], None, False),
        ("what's the weather like", ["assistant"], None, False),
        ("当时我说什么", None, "当时", False),
        ("当时我说什么", [], "当时", False),
    ],
)
def test_cues_and_prior_context_control_only_conversation_routing(query, roles, cue, active):
    turns = (
        None
        if roles is None
        else [
            ConversationTurn(role=role, content="earlier turn", timestamp=float(index * 100))
            for index, role in enumerate(roles)
        ]
    )
    result = resolve(query=query, conversation_context=turns)
    assert result.is_indexical is active
    assert result.cue_matched == cue
    assert result.force_mode == ("episode_recall" if active else None)
    assert result.l1_retrieval_scope == ("conversation_only" if active else None)
    # The consumer only treats sufficiently confident matches as authoritative.
    assert (result.confidence >= 0.9) is active
