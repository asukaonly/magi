"""Combined rule and LLM intent decider for hybrid memory retrieval."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Any, Optional

from magi.utils.calendar_timezone import local_calendar_timezone_id

from .query_temporal import resolve_query_temporal
from .answerability import extract_query_tokens
from .intent_evaluation import EvaluationRecord, compute_diff
from .llm_intent import LLMIntentDecider, LLMRefinement
from .models import IntentDeciderInput, IntentDecision
from .mode_registry import VALID_MODES
from .rule_intent_decider import RuleBasedIntentDecider

logger = logging.getLogger(__name__)

_FAST_PATH_ALLOWED_MODES = frozenset({"event_stream", "exact_fact"})
_FAST_PATH_EN_COMPLEXITY_TOKENS = frozenset({
    "who",
    "why",
    "how",
    "what",
    "when",
    "where",
    "which",
    "compare",
    "comparison",
    "summary",
    "summarize",
    "recap",
    "change",
    "changed",
    "prefer",
    "preference",
    "preferences",
    "like",
    "likes",
    "dislike",
    "dislikes",
    "both",
    "common",
    "share",
    "shared",
    "all",
    "every",
    "count",
    "many",
    "not",
    "without",
    "never",
    "except",
    "boss",
    "colleague",
    "friend",
})
_FAST_PATH_ZH_COMPLEXITY_MARKERS = (
    "多少",
    "几个",
    "哪些",
    "什么",
    "为什么",
    "怎么",
    "是否",
    "有没有",
    "喜欢",
    "偏好",
    "讨厌",
    "总结",
    "概括",
    "对比",
    "比较",
    "变化",
    "还是",
    "共同",
    "所有",
    "全部",
    "不要",
    "并非",
    "没有",
    "同事",
    "老板",
    "朋友",
    "的",
)
_FAST_PATH_DISALLOWED_CHARS = ('?', '？', '"', "'", '《', '》', '「', '」')


def _is_simple_direct_lookup(
    inp: IntentDeciderInput,
    rule_decision: IntentDecision,
) -> bool:
    """Return True when a query has an explicit caller time window and concise keywords.

    Simple explicit-range keyword lookups bypass the auxiliary intent LLM call
    and go straight to FTS + vector retrieval. Point-in-time ``as_of`` queries,
    multi-hop / preference / aggregation / negated prose questions, and
    unbounded natural-language questions continue through the LLM decider.
    """
    if inp.query_mode_hint is not None and inp.query_mode_hint not in _FAST_PATH_ALLOWED_MODES:
        return False
    time_range = rule_decision.time_range
    if (
        time_range is None
        or time_range.as_of is not None
        or (time_range.start is None and time_range.end is None)
    ):
        return False
    query = str(inp.query or "").strip()
    if not query or len(query) > 64:
        return False
    if any(ch in query for ch in _FAST_PATH_DISALLOWED_CHARS):
        return False
    if any(marker in query for marker in _FAST_PATH_ZH_COMPLEXITY_MARKERS):
        return False
    tokens = extract_query_tokens(query)
    if not tokens or len(tokens) > 6:
        return False
    if any(token in _FAST_PATH_EN_COMPLEXITY_TOKENS for token in tokens):
        return False
    return True


class IntentDecider:
    """Combined intent decider: rule fast-path + LLM primary + rule shadow."""

    def __init__(
        self,
        *,
        rule_engine: RuleBasedIntentDecider,
        llm_decider: Optional[LLMIntentDecider] = None,
        llm_enabled: bool = True,
        shadow_eval_enabled: bool = True,
        fast_path_enabled: bool = True,
        eval_callback: Optional[Any] = None,
    ):
        self._rule_engine = rule_engine
        self._llm_decider = llm_decider
        self._llm_enabled = llm_enabled and llm_decider is not None
        self._shadow_eval_enabled = shadow_eval_enabled
        self._fast_path_enabled = bool(fast_path_enabled)
        self._eval_callback = eval_callback
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def decide(self, inp: IntentDeciderInput) -> IntentDecision:
        """Produce final intent decision: typed semantic intent + host-owned routing."""
        query_anchor = time.time()
        query_timezone = local_calendar_timezone_id()
        rule_decision = self._rule_engine.evaluate(inp)

        if self._fast_path_enabled and _is_simple_direct_lookup(inp, rule_decision):
            rule_decision.source = "rule_fast_path"
            rule_decision.reasoning = (
                f"{rule_decision.reasoning}; fast_path=explicit_time_keyword"
                if rule_decision.reasoning
                else "fast_path=explicit_time_keyword"
            )
            return rule_decision

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
            resolved_input = inp
            if inp.query_mode_hint not in VALID_MODES and llm_refinement.query_mode in VALID_MODES:
                resolved_input = replace(inp, query_mode_hint=llm_refinement.query_mode)
            routed_decision = self._rule_engine.evaluate(resolved_input)
            final_decision = self._llm_decider.apply(
                original_query=inp.query,
                rule_decision=routed_decision,
                refinement=llm_refinement,
            )
            # Caller data remains authoritative, even when invalid or empty.
            time_range = rule_decision.time_range
            if inp.raw_time_range is None:
                time_range = resolve_query_temporal(
                    llm_refinement.query_temporal,
                    query=inp.query,
                    anchor_timestamp=query_anchor,
                    timezone_id=query_timezone,
                )
            final_decision.time_range = time_range
            for plan in final_decision.plans:
                plan.time_range = time_range
            decision_source = "llm"
        else:
            final_decision = rule_decision
            decision_source = "rule_fallback"

        final_decision.source = decision_source

        if self._shadow_eval_enabled and self._eval_callback is not None:
            refinement_applied, diff_summary = compute_diff(rule_decision, llm_refinement, final_decision=final_decision)
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
