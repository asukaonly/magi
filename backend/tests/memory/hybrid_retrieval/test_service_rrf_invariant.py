"""Regression test for Phase 4 RRF-profile invariant.

The original code's comment said: 'Only apply RRF overrides when
query_mode was explicitly provided by the caller. Auto-classified modes
use default weights to avoid keyword-heuristic errors distorting
retrieval.' Phase 4's infer_query_mode broke this invariant by
reassigning request.query_mode for inferred modes, which made the
``mode_explicit = bool(resolved_mode)`` guard fire for heuristic-inferred
modes as well.

The fix tracks caller-supplied vs inferred separately and only applies
RRF overrides for caller-supplied (or indexical-override) modes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from magi.memory.hybrid_retrieval.models import (
    ConversationTurn,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.service import HybridRetrievalService


def _memory_with_l1_store() -> MagicMock:
    """Memory mock that has a truthy ``l1`` store so the service builds an
    L1Handler (the RRF override branch requires ``self._l1 is not None``)."""
    mem = MagicMock()
    mem.l0 = None
    # Truthy L1 store with the minimal attribute surface L1Handler.__init__
    # touches. The store itself isn't called during the RRF branch — only
    # the *handler* is — but it must remain identity-stable across refresh
    # calls so _refresh_handlers doesn't rebuild and discard our patches.
    mem.l1 = MagicMock(name="l1_store")
    mem.l2 = None
    mem.l2_entity_catalog = None
    mem.l3 = None
    mem.l4 = None
    return mem


def _patch_l1_with_config_tracker(svc: HybridRetrievalService) -> MagicMock:
    """Replace ``svc._l1.with_config`` with a mock returning a sentinel
    handler so the RRF branch's ``adapted_config is not self._config`` and
    handler reassignment both succeed. The downstream
    ``with_l1_retrieval_scopes`` call on the returned handler must also
    succeed (it's invoked when mode_plan.l1_retrieval_scopes is set)."""
    assert svc._l1 is not None, "expected L1Handler to be built"
    adapted_handler = MagicMock(name="l1_handler_adapted")
    adapted_handler.with_l1_retrieval_scopes.return_value = adapted_handler
    svc._l1.with_config = MagicMock(return_value=adapted_handler)
    # Also stub the scopes call on the original handler (used when no RRF
    # override fires but mode_plan.l1_retrieval_scopes is set).
    svc._l1.with_l1_retrieval_scopes = MagicMock(return_value=svc._l1)
    return adapted_handler


@pytest.mark.asyncio
async def test_inferred_mode_does_not_apply_rrf_profile_override():
    """When query_mode is None and infer_query_mode picks 'summary' from a
    cue like '总结', the RRF profile MUST NOT be overridden — that would
    distort retrieval based on a heuristic guess.
    """
    request = RetrievalQuery(
        query="总结一下我最近的活动",  # '总结' → infer "summary"
        query_mode=None,
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _memory_with_l1_store(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    _patch_l1_with_config_tracker(svc)
    payload = await svc.query(request)

    assert isinstance(payload, RetrievalPayload)
    # Inference fired — confirms we're exercising the right path.
    assert payload.trace.get("mode_source") == "inferred"
    assert payload.trace.get("inferred_mode") == "summary"
    # CORE INVARIANT: inferred mode must NOT swap RRF weights.
    assert payload.trace.get("mode_rrf_applied") is not True, (
        "Heuristic-inferred mode should not drive RRF profile selection — "
        "trace[mode_rrf_applied] must be absent or False, not True."
    )


@pytest.mark.asyncio
async def test_caller_supplied_mode_applies_rrf_profile_override():
    """Counterpart: when the caller explicitly passes query_mode='summary',
    the summary RRF profile IS applied (preserving the original intent).
    """
    request = RetrievalQuery(
        query="anything",
        query_mode="summary",  # caller-supplied — authoritative
        conversation_context=None,
    )
    svc = HybridRetrievalService(
        _memory_with_l1_store(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    _patch_l1_with_config_tracker(svc)
    payload = await svc.query(request)

    assert payload.trace.get("mode_source") == "caller"
    assert payload.trace.get("resolved_query_mode") == "summary"
    # CORE INVARIANT: caller-supplied mode IS authoritative for RRF.
    assert payload.trace.get("mode_rrf_applied") is True, (
        "Caller-supplied mode must apply the mode-specific RRF profile — "
        "trace[mode_rrf_applied] must be True."
    )


@pytest.mark.asyncio
async def test_indexical_override_applies_rrf_profile():
    """Indexical-overridden mode is authoritative (resolver confidence
    >= 0.9 on temporal cues like '当时') — RRF profile applies even
    though the caller did not directly request episode_recall.
    """
    T = 1700000100.0
    request = RetrievalQuery(
        query="当时我说什么",
        query_mode=None,  # caller omitted — but indexical resolver overrides
        conversation_context=[
            ConversationTurn(role="user", content="q", timestamp=T - 30),
            ConversationTurn(role="assistant", content="a", timestamp=T),
        ],
    )
    svc = HybridRetrievalService(
        _memory_with_l1_store(),
        config=RetrievalConfig(intent_decider_llm_enabled=False),
    )
    _patch_l1_with_config_tracker(svc)
    payload = await svc.query(request)

    # Indexical fired and overrode to episode_recall.
    assert payload.trace.get("indexical_resolved") is True
    assert payload.trace.get("resolved_query_mode") == "episode_recall"
    assert payload.trace.get("mode_source") == "indexical_override"
    # CORE INVARIANT: indexical override is authoritative → RRF applies.
    assert payload.trace.get("mode_rrf_applied") is True, (
        "Indexical-override mode is authoritative (resolver confidence "
        ">= 0.9) and MUST apply the mode-specific RRF profile."
    )
