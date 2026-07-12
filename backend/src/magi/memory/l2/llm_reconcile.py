"""Entity reconcile prompt execution for L2."""

from __future__ import annotations

from .models import (
    L2ReconcileAssertion,
    L2ReconcileEntity,
    L2ReconcileGraphFact,
    L2SourceEvent,
    ReconciledTraitOutcome,
)
from .pipeline.prompts import ENTITY_RECONCILE_SYSTEM_PROMPT, render_entity_reconcile_prompt


class L2LLMReconcileMixin:
    """Execute L2 entity reconcile prompts and normalize outcomes."""

    async def reconcile_entity_state(
        self,
        *,
        entity: L2ReconcileEntity,
        graph_facts: list[L2ReconcileGraphFact],
        assertions: list[L2ReconcileAssertion],
        recent_events: list[L2SourceEvent],
    ) -> list[ReconciledTraitOutcome]:
        payload = await self._generate_json(
            system_prompt=ENTITY_RECONCILE_SYSTEM_PROMPT,
            prompt=render_entity_reconcile_prompt(
                entity=entity,
                graph_facts=graph_facts,
                assertions=assertions,
                recent_events=recent_events,
            ),
            request_kind="memory:l2_entity_reconcile",
            turn_id=entity.entity_id,
            required_fields={"reconciled_traits": list},
        )
        outcomes = payload.get("reconciled_traits")
        if not isinstance(outcomes, list):
            return []
        normalized_outcomes: list[ReconciledTraitOutcome] = []
        for item in outcomes:
            if not isinstance(item, dict):
                continue
            try:
                normalized_outcomes.append(ReconciledTraitOutcome(**item))
            except Exception:
                continue
        return normalized_outcomes


__all__ = ["L2LLMReconcileMixin"]
