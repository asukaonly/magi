"""LLM refinement contract for hybrid retrieval intent decisions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
)
from .l2_intent import (
    _VALID_PREDICATE_FAMILIES,
    _VALID_SUBJECT_HINTS,
    _parse_semantic_frame,
    enrich_l2_conditions,
)
from .models import (
    IntentDeciderInput,
    IntentDecision,
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
)

logger = logging.getLogger(__name__)

_LLM_SYSTEM_PROMPT = """\
You are a fast memory-retrieval refinement agent.

The host has already chosen which memory layers to query (L1/L2/L3/L4) based on the
caller's ``query_mode``. Your job is to **refine** the retrieval inputs that will be
applied to those layers, not to re-decide the routing.

You produce a single refinement object that is applied to every routed plan:

- ``content_query``: the answer-oriented retrieval phrase. Must match the user's
  query language. Do not hallucinate, do not expand with invented details, do not
  replace quoted titles with broad topics. Keep it tight.
- ``entities`` (optional, L2): proper-noun mentions in the query.
- ``subject_hint`` (optional, L2): "self" when the user is asking about themselves,
  "explicit" when an entity is mentioned, "none" otherwise.
- ``predicate_family`` (optional, L2): one of ``preference``, ``profile_fact``,
  ``relationship``, ``activity``, ``unknown``.
- ``semantic_frame`` (optional, L2): structured query semantics with the schema:
    {
      "query_family": "affinity" | "relationship" | "profile" | "activity" | "lookup",
      "subject_scope": "self" | "explicit" | "none",
      "answer_kind": "creator" | "place" | "topic" | "person" | "software" | "unknown",
      "answer_unit": "identity" | "presence" | "place" | "topic" | "mixed",
      "entity_mentions": [string, ...],
      "constraints": [{"scope": "target"|"interaction",
                       "facet": "platform"|"located_in"|"category",
                       "raw_value": string,
                       "resolved_entity_id": string?,
                       "resolved_facet_value": string?}],
      "ranking_mode": "confidence" | string
    }
- ``reasoning``: brief one-sentence explanation.

Rules:
- Time range parsing is handled elsewhere. Do not output time ranges.
- Layer routing is handled elsewhere. Do not output a ``layers`` array.
- For comparison questions ("X 还是 Y"), keep both candidates explicit in
  ``content_query``.
- Keep quoted titles verbatim.

Return JSON only:
{
  "content_query": "string",
  "entities": ["string", ...],
  "subject_hint": "self" | "explicit" | "none",
  "predicate_family": "preference" | "profile_fact" | "relationship" | "activity" | "unknown",
  "semantic_frame": { ... } | null,
  "reasoning": "string"
}"""


@dataclass
class LLMRefinement:
    """Flat retrieval-refinement object produced by :class:`LLMIntentDecider`.

    The host's rule engine owns layer routing — this object only refines
    *how* each routed layer is queried. Fields are optional and applied
    selectively per layer (e.g. ``entities`` and ``semantic_frame`` only
    affect L2 plans).
    """

    content_query: str = ""
    entities: Optional[list[str]] = None
    subject_hint: Optional[str] = None
    predicate_family: Optional[str] = None
    semantic_frame: Optional[L2SemanticFrame] = None
    reasoning: str = ""


class LLMIntentDecider:
    """LLM-based retrieval refinement.

    The rule engine owns layer routing (driven by the caller's
    ``query_mode``); this decider contributes *retrieval refinements*
    (``content_query``, ``entities``, ``subject_hint``,
    ``predicate_family``, ``semantic_frame``) that are applied onto the
    rule-routed plans.
    """

    def __init__(self, provider_bridge: Any, *, timeout_seconds: float = 3.0):
        self._bridge = provider_bridge
        self._timeout = timeout_seconds

    async def evaluate(self, inp: IntentDeciderInput) -> LLMRefinement | None:
        """Call the LLM for retrieval refinements. Returns ``None`` on any failure."""
        prompt_lines = [f"user query: {inp.query}"]
        if inp.query_mode_hint:
            prompt_lines.append(f"query_mode_hint: {inp.query_mode_hint}")
        if inp.source_filters:
            prompt_lines.append(f"source_filters_hint: {json.dumps(inp.source_filters, ensure_ascii=False)}")
        if inp.domain_filters:
            prompt_lines.append(f"domain_filters_hint: {json.dumps(inp.domain_filters, ensure_ascii=False)}")
        user_prompt = "\n".join(prompt_lines)
        model = getattr(getattr(self._bridge, "llm", None), "model_name", "unknown")
        base_url = str(getattr(getattr(self._bridge, "llm", None), "base_url", "unknown"))
        t0 = time.monotonic()
        try:
            raw = await self._bridge.chat(
                system_prompt=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=512,
                temperature=0.3,
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=self._timeout,
                event_context={
                    "request_kind": "memory:hybrid_retrieval_intent",
                    "agent_id": "memory:hybrid_retrieval",
                },
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "LLM intent decider completed model=%s base_url=%s elapsed_ms=%.1f timeout=%s prompt_len=%d",
                model, base_url, elapsed_ms, self._timeout, len(user_prompt),
            )
            return self._parse_response(raw)
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "LLM intent decider failed model=%s base_url=%s elapsed_ms=%.1f timeout=%s prompt_len=%d"
                "\n  disable_thinking=True json_mode=True max_tokens=512 temperature=0.3"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                model, base_url, elapsed_ms, self._timeout, len(user_prompt),
                _LLM_SYSTEM_PROMPT, user_prompt,
                exc_info=True,
            )
            return None

    def _parse_response(self, raw: str) -> LLMRefinement | None:
        """Parse the LLM JSON response into a :class:`LLMRefinement`."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM intent decider returned invalid JSON")
            return None
        if not isinstance(data, dict):
            return None

        content_query = str(data.get("content_query") or "").strip()
        entities_raw = data.get("entities")
        entities: Optional[list[str]] = None
        if isinstance(entities_raw, list):
            entities = [str(entity) for entity in entities_raw if isinstance(entity, (str, int, float))]
            entities = [entity for entity in entities if entity]
            if not entities:
                entities = None

        subject_hint_raw = data.get("subject_hint")
        subject_hint = (
            str(subject_hint_raw)
            if isinstance(subject_hint_raw, str) and subject_hint_raw in _VALID_SUBJECT_HINTS
            else None
        )

        predicate_family_raw = data.get("predicate_family")
        predicate_family = (
            str(predicate_family_raw)
            if isinstance(predicate_family_raw, str) and predicate_family_raw in _VALID_PREDICATE_FAMILIES
            else None
        )

        semantic_frame = _parse_semantic_frame(data.get("semantic_frame"))
        reasoning = str(data.get("reasoning") or "")

        if not content_query and entities is None and semantic_frame is None:
            return None

        return LLMRefinement(
            content_query=content_query,
            entities=entities,
            subject_hint=subject_hint,
            predicate_family=predicate_family,
            semantic_frame=semantic_frame,
            reasoning=reasoning,
        )

    def apply(
        self,
        *,
        original_query: str,
        rule_decision: IntentDecision,
        refinement: LLMRefinement,
    ) -> IntentDecision:
        """Apply ``refinement`` onto the rule-routed plans."""
        refined_query = (refinement.content_query or "").strip()
        for plan in rule_decision.plans:
            conditions = plan.conditions
            if plan.layer == "L1" and isinstance(conditions, L1Conditions):
                conditions.content_query = self._validate_l1_content_query(
                    original_query=original_query,
                    content_query=refined_query or conditions.content_query,
                )
            elif plan.layer == "L2" and isinstance(conditions, L2Conditions):
                if refined_query:
                    conditions.content_query = refined_query
                if refinement.entities is not None:
                    conditions.entities = refinement.entities
                if refinement.subject_hint is not None:
                    conditions.subject_hint = refinement.subject_hint
                if refinement.predicate_family is not None:
                    conditions.predicate_family = refinement.predicate_family
                if refinement.semantic_frame is not None:
                    conditions.semantic_frame = refinement.semantic_frame
                enrich_l2_conditions(conditions, original_query)
            elif plan.layer == "L3" and isinstance(conditions, L3Conditions):
                if refined_query:
                    conditions.content_query = refined_query
            elif plan.layer == "L4" and isinstance(conditions, L4Conditions):
                if refined_query:
                    conditions.content_query = refined_query

        merged_reasoning = rule_decision.reasoning
        if refinement.reasoning:
            merged_reasoning = (
                f"{merged_reasoning}; llm: {refinement.reasoning}"
                if merged_reasoning
                else f"llm: {refinement.reasoning}"
            )
        rule_decision.reasoning = merged_reasoning
        rule_decision.source = "llm"
        return rule_decision

    @staticmethod
    def _validate_l1_content_query(*, original_query: str, content_query: str) -> str:
        """Rewrite clearly over-broad L1 queries back to the original user query."""
        normalized_query = str(original_query or "").strip()
        normalized_content_query = str(content_query or "").strip()
        if not normalized_query:
            return normalized_content_query
        if not normalized_content_query:
            return normalized_query

        content_tokens = set(extract_query_tokens(normalized_content_query))
        normalized_content = " ".join(extract_query_tokens(normalized_content_query))

        quoted_spans = extract_quoted_spans(normalized_query)
        if quoted_spans and not any(span and span in normalized_content for span in quoted_spans):
            return normalized_query

        comparison_spans = extract_comparison_spans(normalized_query)
        if comparison_spans:
            has_comparison_coverage = any(
                set(extract_query_tokens(span)).issubset(content_tokens)
                for span in comparison_spans
                if span
            )
            if not has_comparison_coverage:
                return normalized_query

        original_tokens = set(extract_query_tokens(normalized_query))
        if original_tokens:
            prefix_len = 5

            def overlaps_original(token: str) -> bool:
                for original_token in original_tokens:
                    if token == original_token:
                        return True
                    if (
                        len(token) >= prefix_len
                        and len(original_token) >= prefix_len
                        and token[:prefix_len] == original_token[:prefix_len]
                    ):
                        return True
                return False

            novel_count = sum(1 for token in content_tokens if not overlaps_original(token))
            if novel_count > len(original_tokens):
                return normalized_query

        return normalized_content_query