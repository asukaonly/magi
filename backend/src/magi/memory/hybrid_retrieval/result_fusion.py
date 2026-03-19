"""Result fusion: deduplication and token-budget truncation."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .models import RetrievalConfig, RetrievalPayload

logger = logging.getLogger(__name__)


def estimate_tokens(items: List[Dict[str, Any]], char_per_token: float = 3.0) -> int:
    """Estimate token count from a list of dict items using char-ratio."""
    total_chars = 0
    for item in items:
        for v in item.values():
            total_chars += len(str(v))
    return int(total_chars / char_per_token)


def truncate_to_budget(
    items: List[Dict[str, Any]],
    budget_tokens: float,
    char_per_token: float = 3.0,
) -> List[Dict[str, Any]]:
    """Truncate a list of items to fit within a token budget."""
    if budget_tokens <= 0:
        return []
    result: list[Dict[str, Any]] = []
    used = 0.0
    for item in items:
        item_tokens = estimate_tokens([item], char_per_token)
        if used + item_tokens > budget_tokens:
            break
        result.append(item)
        used += item_tokens
    return result


class ResultFusion:
    """Deduplicate and apply token-budget truncation to RetrievalPayload."""

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self._config = config or RetrievalConfig()

    def apply(
        self,
        payload: RetrievalPayload,
        max_tokens: int | None = None,
    ) -> RetrievalPayload:
        """Deduplicate and truncate payload within token budget."""
        # 1. Dedup
        payload = self._dedup(payload)

        # 2. Token budget truncation
        budget = max_tokens or self._config.default_max_tokens
        cpt = self._config.char_per_token_ratio
        payload = self._apply_budget(payload, budget, cpt)

        return payload

    def _dedup(self, payload: RetrievalPayload) -> RetrievalPayload:
        """Remove duplicate items across layers."""
        # L1 events: dedup by event_id
        payload.l1_events = self._dedup_by_key(payload.l1_events, "event_id")

        # L2 entity cards: dedup by entity_id
        payload.l2_entity_cards = self._dedup_by_key(payload.l2_entity_cards, "entity_id")
        payload.l2_assertions = self._dedup_by_key(payload.l2_assertions, "assertion_id")

        # L3 reflections: dedup by summary_id or id
        payload.l3_reflections = self._dedup_by_key(payload.l3_reflections, "summary_id", "id")

        # L4 procedures: dedup by id
        payload.l4_procedures = self._dedup_by_key(payload.l4_procedures, "id")

        return payload

    @staticmethod
    def _dedup_by_key(items: List[Dict[str, Any]], *keys: str) -> List[Dict[str, Any]]:
        """Dedup a list of dicts by the first matching key."""
        seen: set[str] = set()
        result: list[Dict[str, Any]] = []
        for item in items:
            item_id = None
            for key in keys:
                if key in item:
                    item_id = str(item[key])
                    break
            if item_id is None:
                result.append(item)
                continue
            if item_id not in seen:
                seen.add(item_id)
                result.append(item)
        return result

    @staticmethod
    def _apply_budget(
        payload: RetrievalPayload,
        budget: int,
        char_per_token: float,
    ) -> RetrievalPayload:
        """Apply token budget in priority order: L0 > L2 > L4 > L3 > L1."""
        remaining = float(budget)

        # L0: full (usually small)
        remaining -= estimate_tokens(payload.l0_workbench, char_per_token)

        # L2: full
        l2_all = payload.l2_entity_cards + payload.l2_relationships + payload.l2_assertions
        remaining -= estimate_tokens(l2_all, char_per_token)

        # L4: up to 20% of remaining
        l4_budget = remaining * 0.2
        payload.l4_procedures = truncate_to_budget(
            payload.l4_procedures, l4_budget, char_per_token,
        )
        remaining -= estimate_tokens(payload.l4_procedures, char_per_token)

        # L3: up to 30% of remaining
        l3_budget = remaining * 0.3
        payload.l3_reflections = truncate_to_budget(
            payload.l3_reflections, l3_budget, char_per_token,
        )
        remaining -= estimate_tokens(payload.l3_reflections, char_per_token)

        # L1: eats the rest
        payload.l1_events = truncate_to_budget(
            payload.l1_events, remaining, char_per_token,
        )

        return payload
