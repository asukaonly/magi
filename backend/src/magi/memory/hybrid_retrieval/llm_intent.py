"""LLM refinement contract for hybrid retrieval intent decisions."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal, Optional

EvidenceFocus = Literal["declared", "observed", "both"]
_VALID_EVIDENCE_FOCI: frozenset[str] = frozenset(("declared", "observed", "both"))

from .answerability import (
    extract_comparison_spans,
    extract_query_tokens,
    extract_quoted_spans,
)
from .evidence_routing import classes_from_focus, infer_allowed_evidence_classes
from .l2_intent import (
    _VALID_PREDICATE_FAMILIES,
    _VALID_SUBJECT_HINTS,
    _parse_semantic_frame,
    enrich_l2_conditions,
    mentions_from_semantic_frame,
    predicate_family_from_query_family,
    subject_hint_from_semantic_frame,
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

You produce a single refinement object that is applied to every routed plan. Keep
the object compact. semantic_frame is authoritative for L2 entity roles; do
not also output duplicate top-level ``entities``, ``subject_hint``, or
``predicate_family``.

- ``content_query``: the answer-oriented retrieval phrase. Must match the user's
  query language. Do not hallucinate, do not expand with invented details, do not
  replace quoted titles with broad topics. Keep it tight.
- ``relation_intent`` (optional, L2): a short ENGLISH, relation-oriented phrase
  describing the main relation needed for the first hop. Always output in English
  even when the query is in another language because it is matched against an
  English predicate vocabulary. Examples: "likes / is fond of",
  "works with / is a colleague of", "talks about / discusses",
  "listening to / consuming media". Leave null when no clear relation is implied.
- ``hop2_target_type`` (optional, L2): set this whenever reaching the answer
  requires first resolving an INTERMEDIATE entity — the question asks for a
  property or relation OF some entity that itself must be derived from the user,
  rather than relating to the user directly. This is a STRUCTURAL property of the
  question and is INDEPENDENT of query_mode_hint: a question can want a single
  exact answer and still take two hops. Detect it from the question's structure in
  ANY language, especially possessive/relational chains where one entity is
  qualified by another — e.g. "the boss of my colleague" / "我同事的老板" (resolve
  the colleague first, then their boss), or "albums of the artists I like" / "我喜欢
  的歌手的专辑" (resolve the artists first, then their albums). Set it to the FINAL
  answer's entity type, one of: "media" | "person" | "place" | "software" |
  "topic". Leave null only for direct one-hop questions where the answer relates to
  the user themselves (e.g. "what music do I like" → null).
- ``evidence_focus`` (optional, L2): when the user is asking about themselves
  (subject_hint="self"), classify what evidence tier the question wants:
    * ``"declared"`` — user is asking about what they explicitly said/claimed
      in conversation. Examples: "what music do I like", "what name did I tell
      you", "what are my preferences".
    * ``"observed"`` — user is asking about their own behavior captured from
      external sources (Chrome history, app usage). Examples: "what companies
      did I browse", "what sites did I visit most".
    * ``"both"`` — both declared and observed legitimately apply. Example:
      "what am I into right now".
  Leave null when the query isn't self-referential or the tier is genuinely
  unclear. This field is preferred over predicate_family for evidence filtering.
- ``semantic_frame`` (optional, L2): structured query semantics with the schema:
    {
      "query_family": "affinity" | "relationship" | "profile" | "activity" | "lookup",
      "subject_scope": "self" | "explicit" | "multi" | "none",
      "subject_mode": "self" | "single" | "multi" | "none",
      "relation_shape": "single_fact" | "shared_fact" | "between_people" |
                        "comparison" | "two_hop" | "unknown",
      "subject_mentions": [string, ...],
      "object_mentions": [string, ...],
      "entity_mentions": [string, ...],
      "answer_kind": "creator" | "place" | "topic" | "person" | "software" |
                     "media" | "unknown",
      "constraints": [{"scope": "target"|"interaction",
                       "facet": "platform"|"located_in"|"category",
                       "raw_value": string}]
    }
  Role rules:
    * Use subject_mode="self" only for actual first-person queries ("I", "my",
      "我", "我的"). Third-party dialogue speakers are not the local user.
    * Use subject_mode="single" + subject_mentions for "What does A think about
      B?", "Where did A go?", or one named person's facts.
    * Use subject_mode="multi" + relation_shape="shared_fact" for questions
      asking what multiple people both/share/have in common.
    * Use relation_shape="between_people" when the question is about A's relation,
      feeling, or action toward B; put A in subject_mentions and B in object_mentions.
- ``reasoning``: brief one-sentence explanation.

Rules:
- Time range parsing is handled elsewhere. Do not output time ranges.
- Layer routing is handled elsewhere. Do not output a ``layers`` array.
- Do not output top-level ``entities``, ``subject_hint``, or ``predicate_family``;
  the host derives them from semantic_frame.
- For comparison questions ("X 还是 Y"), keep both candidates explicit in
  ``content_query``.
- Keep quoted titles verbatim.

Return JSON only:
{
  "content_query": "string",
  "relation_intent": "string | null",
  "hop2_target_type": "string | null",
  "evidence_focus": "declared" | "observed" | "both" | null,
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
    relation_intent: Optional[str] = None
    hop2_target_type: Optional[str] = None
    evidence_focus: Optional[EvidenceFocus] = None
    semantic_frame: Optional[L2SemanticFrame] = None
    reasoning: str = ""


@dataclass(frozen=True)
class _SemanticRefinement:
    entities: list[str]
    subject_hint: str | None
    predicate_family: str | None


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
            prompt_lines.append(
                f"source_filters_hint: {json.dumps(inp.source_filters, ensure_ascii=False)}"
            )
        if inp.domain_filters:
            prompt_lines.append(
                f"domain_filters_hint: {json.dumps(inp.domain_filters, ensure_ascii=False)}"
            )
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
                model,
                base_url,
                elapsed_ms,
                self._timeout,
                len(user_prompt),
            )
            return self._parse_response(raw)
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "LLM intent decider failed model=%s base_url=%s elapsed_ms=%.1f timeout=%s prompt_len=%d"
                "\n  disable_thinking=True json_mode=True max_tokens=512 temperature=0.3"
                "\n  system_prompt:\n%s"
                "\n  user_prompt:\n%s",
                model,
                base_url,
                elapsed_ms,
                self._timeout,
                len(user_prompt),
                _LLM_SYSTEM_PROMPT,
                user_prompt,
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
            entities = [
                str(entity) for entity in entities_raw if isinstance(entity, (str, int, float))
            ]
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
            if isinstance(predicate_family_raw, str)
            and predicate_family_raw in _VALID_PREDICATE_FAMILIES
            else None
        )

        relation_intent_raw = data.get("relation_intent")
        relation_intent = (
            str(relation_intent_raw).strip()
            if isinstance(relation_intent_raw, str) and str(relation_intent_raw).strip()
            else None
        )

        hop2_target_type_raw = data.get("hop2_target_type")
        hop2_target_type = (
            str(hop2_target_type_raw).strip()
            if isinstance(hop2_target_type_raw, str) and str(hop2_target_type_raw).strip()
            else None
        )

        evidence_focus_raw = data.get("evidence_focus")
        evidence_focus: Optional[EvidenceFocus] = None
        if isinstance(evidence_focus_raw, str) and evidence_focus_raw in _VALID_EVIDENCE_FOCI:
            evidence_focus = evidence_focus_raw  # type: ignore[assignment]

        semantic_frame = _parse_semantic_frame(data.get("semantic_frame"))
        if entities is None and semantic_frame is not None:
            entities = mentions_from_semantic_frame(semantic_frame) or None
        if subject_hint is None and semantic_frame is not None:
            subject_hint = subject_hint_from_semantic_frame(semantic_frame)
        if predicate_family is None and semantic_frame is not None:
            predicate_family = predicate_family_from_query_family(semantic_frame.query_family)
        reasoning = str(data.get("reasoning") or "")

        if not content_query and entities is None and semantic_frame is None:
            return None

        return LLMRefinement(
            content_query=content_query,
            entities=entities,
            subject_hint=subject_hint,
            predicate_family=predicate_family,
            relation_intent=relation_intent,
            hop2_target_type=hop2_target_type,
            evidence_focus=evidence_focus,
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
                self._apply_l1_refinement(original_query, refined_query, conditions)
            elif plan.layer == "L2" and isinstance(conditions, L2Conditions):
                self._apply_l2_refinement(original_query, refined_query, refinement, conditions)
            elif plan.layer == "L3" and isinstance(conditions, L3Conditions):
                self._apply_content_query_refinement(refined_query, conditions)
            elif plan.layer == "L4" and isinstance(conditions, L4Conditions):
                self._apply_content_query_refinement(refined_query, conditions)

        rule_decision.reasoning = _merge_reasoning(rule_decision.reasoning, refinement.reasoning)
        rule_decision.source = "llm"
        return rule_decision

    def _apply_l1_refinement(
        self,
        original_query: str,
        refined_query: str,
        conditions: L1Conditions,
    ) -> None:
        conditions.content_query = self._validate_l1_content_query(
            original_query=original_query,
            content_query=refined_query or conditions.content_query,
        )

    def _apply_l2_refinement(
        self,
        original_query: str,
        refined_query: str,
        refinement: LLMRefinement,
        conditions: L2Conditions,
    ) -> None:
        semantic = _derive_semantic_refinement(refinement)
        if refined_query:
            conditions.content_query = refined_query
        if refinement.entities is not None:
            conditions.entities = refinement.entities
        elif semantic.entities:
            conditions.entities = semantic.entities
        if refinement.subject_hint is not None:
            conditions.subject_hint = refinement.subject_hint
        elif semantic.subject_hint is not None:
            conditions.subject_hint = semantic.subject_hint
        if refinement.predicate_family is not None:
            conditions.predicate_family = refinement.predicate_family
        elif semantic.predicate_family is not None:
            conditions.predicate_family = semantic.predicate_family
        if refinement.relation_intent is not None:
            conditions.relation_intent = refinement.relation_intent
        if refinement.hop2_target_type is not None:
            conditions.hop2_target_type = refinement.hop2_target_type
        if refinement.semantic_frame is not None:
            conditions.semantic_frame = refinement.semantic_frame
        enrich_l2_conditions(conditions, original_query)
        _apply_l2_evidence_refinement(conditions, refinement)

    @staticmethod
    def _apply_content_query_refinement(
        refined_query: str,
        conditions: L3Conditions | L4Conditions,
    ) -> None:
        if refined_query:
            conditions.content_query = refined_query

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


def _derive_semantic_refinement(refinement: LLMRefinement) -> _SemanticRefinement:
    if refinement.semantic_frame is None:
        return _SemanticRefinement(entities=[], subject_hint=None, predicate_family=None)
    return _SemanticRefinement(
        entities=mentions_from_semantic_frame(refinement.semantic_frame) or [],
        subject_hint=subject_hint_from_semantic_frame(refinement.semantic_frame),
        predicate_family=predicate_family_from_query_family(refinement.semantic_frame.query_family),
    )


def _apply_l2_evidence_refinement(conditions: L2Conditions, refinement: LLMRefinement) -> None:
    if conditions.allowed_evidence_classes is not None:
        return
    focused = classes_from_focus(refinement.evidence_focus)
    if focused is not None:
        conditions.allowed_evidence_classes = focused
        conditions.evidence_focus_source = "llm"
        return
    inferred = infer_allowed_evidence_classes(
        predicate_family=conditions.predicate_family,
        subject_scope=conditions.subject_hint,
    )
    if inferred is not None:
        conditions.allowed_evidence_classes = inferred
        conditions.evidence_focus_source = "family_fallback"


def _merge_reasoning(rule_reasoning: str, llm_reasoning: str) -> str:
    if not llm_reasoning:
        return rule_reasoning
    return f"{rule_reasoning}; llm: {llm_reasoning}" if rule_reasoning else f"llm: {llm_reasoning}"
