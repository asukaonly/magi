"""Combined rule and LLM intent decider for hybrid memory retrieval."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .intent_evaluation import EvaluationRecord, compute_diff
from .llm_intent import LLMIntentDecider, LLMRefinement
from .models import IntentDeciderInput, IntentDecision
from .rule_intent_decider import RuleBasedIntentDecider

logger = logging.getLogger(__name__)


class IntentDecider:
    """Combined intent decider: LLM primary + rule shadow + evaluation logging."""

    def __init__(
        self,
        *,
        rule_engine: RuleBasedIntentDecider,
        llm_decider: Optional[LLMIntentDecider] = None,
        llm_enabled: bool = True,
        shadow_eval_enabled: bool = True,
        eval_callback: Optional[Any] = None,
    ):
        self._rule_engine = rule_engine
        self._llm_decider = llm_decider
        self._llm_enabled = llm_enabled and llm_decider is not None
        self._shadow_eval_enabled = shadow_eval_enabled
        self._eval_callback = eval_callback
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def decide(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce final intent decision: rule-canonical routing + LLM refinements."""
        rule_decision = self._rule_engine.evaluate(inp)

        llm_refinement: Optional[LLMRefinement] = None
        llm_latency_ms: Optional[float] = None
        llm_error: Optional[str] = None

        if self._llm_enabled and self._llm_decider is not None:
            started_at = time.monotonic()
            try:
                llm_refinement = await self._llm_decider.evaluate(inp)
            except Exception as exc:
                llm_error = str(exc)
                logger.warning("LLM intent decider error: %s", exc)
            llm_latency_ms = (time.monotonic() - started_at) * 1000

        if llm_refinement is not None and self._llm_decider is not None:
            final_decision = self._llm_decider.apply(
                original_query=inp.query,
                rule_decision=rule_decision,
                refinement=llm_refinement,
            )
            decision_source = "llm"
        else:
            final_decision = rule_decision
            decision_source = "rule_fallback"

        final_decision.source = decision_source

        if self._shadow_eval_enabled and self._eval_callback is not None:
            refinement_applied, diff_summary = compute_diff(rule_decision, llm_refinement)
            record = EvaluationRecord(
                query=inp.query,
                user_id=inp.user_id,
                session_id=inp.session_id,
                rule_decision=rule_decision,
                llm_refinement=llm_refinement,
                final_decision=final_decision,
                decision_source=decision_source,
                llm_latency_ms=llm_latency_ms,
                llm_error=llm_error,
                refinement_applied=refinement_applied,
                diff_summary=diff_summary,
            )
            task = asyncio.create_task(self._safe_log(record))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return final_decision

    async def _safe_log(self, record: EvaluationRecord) -> None:
        """Log evaluation, swallowing errors."""
        try:
            await self._eval_callback(record)
        except Exception:
            logger.debug("Shadow eval logging error", exc_info=True)


__all__ = ["IntentDecider"]
