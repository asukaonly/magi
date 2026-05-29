"""Orchestration strategy helpers (Phase B: most contents removed).

The keyword-based normalization that previously lived here is replaced
by ``RouteDecision`` strict validation and the
``RouteDecision.to_legacy_strategy_dict()`` adapter.

This module is intentionally near-empty during the Phase B migration
window so that any remaining import attempts fail loudly. The file is
fully deleted in a follow-up cleanup once we are confident no internal
or external code path still references it.
"""
from __future__ import annotations


__all__: list[str] = []
