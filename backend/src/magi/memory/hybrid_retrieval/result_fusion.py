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
        payload = self._apply_budget(
            payload,
            budget,
            cpt,
            self._config.l0_max_tokens,
            self._config.l0_budget_ratio,
        )

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
        l0_max_tokens: int,
        l0_budget_ratio: float,
    ) -> RetrievalPayload:
        """Apply token budget in priority order: L0 > L1 > L2 > L3 > L4.

        L1 events are the factual foundation of personal memory and get
        first pick after L0 working context.  L2 entity knowledge, L3
        reflections, and L4 procedures share the remainder.
        """
        remaining = float(budget)

        # L0: preserve priority, but cap its share so other layers still surface.
        l0_budget = min(float(max(l0_max_tokens, 0)), remaining * max(l0_budget_ratio, 0.0))
        payload.l0_workbench = truncate_to_budget(payload.l0_workbench, l0_budget, char_per_token)
        remaining -= estimate_tokens(payload.l0_workbench, char_per_token)

        # L1: primary layer — up to 50% of remaining budget.
        l1_budget = remaining * 0.5
        payload.l1_events = ResultFusion._truncate_l1_with_session_coverage(
            payload.l1_events,
            l1_budget,
            char_per_token,
        )
        remaining -= estimate_tokens(payload.l1_events, char_per_token)

        # L2: up to 40% of remaining (entity cards, relationships, assertions)
        l2_budget = remaining * 0.4
        l2_all = payload.l2_entity_cards + payload.l2_relationships + payload.l2_assertions
        l2_tokens = estimate_tokens(l2_all, char_per_token)
        if l2_tokens > l2_budget:
            payload.l2_entity_cards = truncate_to_budget(payload.l2_entity_cards, l2_budget * 0.3, char_per_token)
            l2_budget_left = l2_budget - estimate_tokens(payload.l2_entity_cards, char_per_token)
            payload.l2_relationships = truncate_to_budget(payload.l2_relationships, l2_budget_left * 0.6, char_per_token)
            l2_budget_left -= estimate_tokens(payload.l2_relationships, char_per_token)
            payload.l2_assertions = truncate_to_budget(payload.l2_assertions, l2_budget_left, char_per_token)
            l2_all = payload.l2_entity_cards + payload.l2_relationships + payload.l2_assertions
        remaining -= estimate_tokens(l2_all, char_per_token)

        # L3: up to 40% of remaining
        l3_budget = remaining * 0.4
        payload.l3_reflections = truncate_to_budget(
            payload.l3_reflections, l3_budget, char_per_token,
        )
        remaining -= estimate_tokens(payload.l3_reflections, char_per_token)

        # L4: eats the rest
        payload.l4_procedures = truncate_to_budget(
            payload.l4_procedures, remaining, char_per_token,
        )

        return payload

    @staticmethod
    def _truncate_l1_with_session_coverage(
        items: List[Dict[str, Any]],
        budget_tokens: float,
        char_per_token: float,
    ) -> List[Dict[str, Any]]:
        """Truncate L1 while preserving high-value anchors across sessions when possible."""
        if budget_tokens <= 0 or not items:
            return []

        ranked_items = ResultFusion._rank_l1_items(items)
        best_by_session: dict[str, Dict[str, Any]] = {}
        for item in ranked_items:
            session_id = str(item.get("session_id") or "").strip()
            if not session_id:
                continue
            best_by_session.setdefault(session_id, item)

        selected: list[Dict[str, Any]] = []
        used = 0.0
        selected_ids: set[str] = set()

        for item in ResultFusion._rank_l1_items(list(best_by_session.values())):
            item_id = str(item.get("event_id") or "")
            item_tokens = estimate_tokens([item], char_per_token)
            if used + item_tokens > budget_tokens:
                continue
            selected.append(item)
            used += item_tokens
            if item_id:
                selected_ids.add(item_id)

        for item in ranked_items:
            item_id = str(item.get("event_id") or "")
            if item_id and item_id in selected_ids:
                continue
            item_tokens = estimate_tokens([item], char_per_token)
            if used + item_tokens > budget_tokens:
                continue
            selected.append(item)
            used += item_tokens
            if item_id:
                selected_ids.add(item_id)

        return selected

    @staticmethod
    def _rank_l1_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rank L1 items by answerability-oriented metadata before truncation."""
        def _sort_key(item: Dict[str, Any]) -> tuple[float, float, int]:
            retrieval_score = float(item.get("retrieval_score") or 0.0)
            timestamp = float(item.get("timestamp") or 0.0)
            author_bonus = 1 if str(item.get("author_type") or "").strip().lower() == "user" else 0
            return (retrieval_score, timestamp, author_bonus)

        return sorted(items, key=_sort_key, reverse=True)
