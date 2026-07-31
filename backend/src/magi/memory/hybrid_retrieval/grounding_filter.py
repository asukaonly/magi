"""Listwise relevance filter for retrieval payloads (LLM-as-reranker).

After hybrid_retrieval has done BM25 + vector + temporal + RRF fusion,
we still hand the chat LLM a list that can run 50-100 L1 events deep
plus L2 candidates. The chat LLM then has to re-judge relevance
inline with answering — bad division of labour: noise dilutes the
final answer, the "调用了 X 条记忆" UI chip shows useless counts, and
the user complains "it found too much stuff that isn't related".

This module sits BETWEEN ``service._execute_query()`` and the answer
LLM. It runs ONE cheap LLM call over a compact candidate summary and
keeps only ids the LLM marked relevant. The kept set then drives both
the projection layer (smaller "[Memory Recall]" string) and the
trace (so the UI chip reflects relevant count, not raw count).

Design contract:

  - This is an **optimization** layer. Any failure (timeout, malformed
    JSON, no bridge wired up, candidates too trivial to compare (combined
    total of 0 or 1 items across l1_events + l2_relationships)) degrades
    silently to "no filtering" — the raw payload flows through unchanged.

  - ONE unified pass: ``l1_events`` and ``l2_relationships`` are judged
    together in a single LLM call with a single keep-set and a single
    trace key (``grounding_filter``). Global indices map back to either
    type after the response arrives. The sub-counts per type are recorded
    inside the trace. The ``grounding_filter_l2`` trace key is written
    as a back-compat alias so callers that read both keys still get data.

  - Consequence of unification: the two passes are NO LONGER independent.
    If the single LLM call degrades (timeout / exception / bad response),
    BOTH lists are returned unchanged together. The old per-type
    failure-independence property is intentionally dropped in exchange
    for halved latency and halved system-prompt token cost.

  - The model call uses ``IntentDecider``-style cheap LLM (qwen-flash
    or similar) injected by the caller. The grounding pass is short
    (sub-3s).

  - **The filter sees the same content the answer LLM will see.**
    Per-candidate content is NOT truncated for prompt-size reasons —
    only by a defensive 4KB cap against pathological inputs. The
    earlier "snippet=content[:80]" design caused silent recall
    failures: OCR records whose key passage started past char 80
    looked irrelevant to the filter and got dropped, so the answer
    LLM never saw them. Token cost is a worthwhile trade for
    eliminating that whole class of bug.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from magi.utils.diagnostic_logging import full_content_logging_enabled

from .debug_detail import event_records, log_detail, relationship_records
from .grounding_filter_owner import (
    apply_named_person_owner_prefilter as _apply_named_person_owner_prefilter,
)
from .grounding_filter_prompt import (
    CONTENT_CAP_CHARS,  # noqa: F401 - compatibility export
    SYSTEM_PROMPT as _SYSTEM_PROMPT,
    build_l2_prompt_payload as _build_l2_prompt_payload,  # noqa: F401
    build_prompt_payload as _build_prompt_payload,  # noqa: F401
    build_unified_prompt_payload as _build_unified_prompt_payload,
    parse_keep_response as _parse_keep_response,
)
from .grounding_filter_trace import (
    compat_l2_trace as _compat_l2_trace,
    degraded_trace as _degraded_trace,
)
from .models import RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)


def _diagnostic_text(value: Any) -> Any:
    if full_content_logging_enabled():
        return value
    return "[content omitted by diagnostics setting]"

# Minimum COMBINED candidate count worth an LLM round-trip. A single
# candidate has nothing to filter against; 2+ can carry noise. NOTE:
# low-recall sets are the MOST important to filter (few hits, often all
# noise), so unlike the previous design we do NOT skip moderate counts —
# only the trivial 0/1 case.
MIN_CANDIDATES_TO_FILTER = 2

# Hard cap on what we'll show the grounding LLM. If retrieval somehow
# delivers 500 candidates, we trim to top SKIP_THRESHOLD_MAX by
# original rank (the head of the RRF-fused list); the trimmed tail
# never had a real chance of being scored by the answer LLM anyway.
# Applied PER TYPE before building the unified candidate list.
SKIP_THRESHOLD_MAX = 60


@dataclass(slots=True)
class _GroundingCandidateWindow:
    query: str
    events: list[dict[str, Any]]
    rels: list[dict[str, Any]]
    sliced_events: list[dict[str, Any]]
    sliced_rels: list[dict[str, Any]]
    total: int


@dataclass(slots=True)
class _ParsedGroundingResponse:
    kept_indices: list[int]
    why: str | None
    valid_ev_indices: list[int]
    valid_rel_indices: list[int]
    event_count: int

    @property
    def has_valid_indices(self) -> bool:
        return bool(self.valid_ev_indices or self.valid_rel_indices)


@dataclass(slots=True)
class _GroundingResponseContext:
    payload: RetrievalPayload
    query: str
    events: list[dict[str, Any]]
    rels: list[dict[str, Any]]
    sliced_events: list[dict[str, Any]]
    sliced_rels: list[dict[str, Any]]
    total: int
    elapsed_ms: float
    owner_screen: dict[str, Any]


class GroundingFilter:
    """Apply an LLM-as-listwise-filter to RetrievalPayload.l1_events
    and RetrievalPayload.l2_relationships in a SINGLE LLM call.

    Instantiated once at service setup; ``apply()`` is the per-query
    entry point. Stateless apart from the LLM bridge handle and the
    timeout knob.

    Both item types are judged together. If the single call degrades
    (timeout / exception / bad response), BOTH lists are returned
    unchanged — the old per-type failure-independence is intentionally
    dropped in exchange for halved latency.
    """

    def __init__(
        self,
        *,
        llm_bridge: Any | None,
        timeout_seconds: float = 3.0,
        enabled: bool = True,
    ) -> None:
        self._bridge = llm_bridge
        self._timeout = float(timeout_seconds)
        self._enabled = bool(enabled) and llm_bridge is not None

    async def apply(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> RetrievalPayload:
        """Filter L1 events and L2 relationships in one pass, returning payload."""
        if not self._enabled:
            return payload

        window = self._candidate_window(payload, request)
        skip_reason = self._skip_reason(window)
        if skip_reason is not None:
            self._write_skip_trace(
                payload,
                query=window.query,
                reason=skip_reason,
                input_count=window.total,
            )
            return payload

        window, owner_screen, owner_completed = self._owner_screened_window(
            payload=payload,
            window=window,
        )
        if owner_completed:
            return payload

        prompt_payload = self._build_logged_prompt(window)
        raw, elapsed_ms = await self._call_grounding_llm(
            payload=payload,
            prompt_payload=prompt_payload,
            total=window.total,
        )
        if raw is None:
            return payload

        return self._apply_llm_response(
            context=_GroundingResponseContext(
                payload=payload,
                query=window.query,
                events=window.events,
                rels=window.rels,
                sliced_events=window.sliced_events,
                sliced_rels=window.sliced_rels,
                total=window.total,
                elapsed_ms=elapsed_ms,
                owner_screen=owner_screen,
            ),
            raw=raw,
        )

    def _candidate_window(
        self,
        payload: RetrievalPayload,
        request: RetrievalQuery,
    ) -> _GroundingCandidateWindow:
        query = str(request.query or "").strip()
        events = payload.l1_events or []
        rels = payload.l2_relationships or []
        sliced_events = events[:SKIP_THRESHOLD_MAX]
        sliced_rels = rels[:SKIP_THRESHOLD_MAX]
        return _GroundingCandidateWindow(
            query=query,
            events=events,
            rels=rels,
            sliced_events=sliced_events,
            sliced_rels=sliced_rels,
            total=len(sliced_events) + len(sliced_rels),
        )

    def _skip_reason(self, window: _GroundingCandidateWindow) -> str | None:
        if window.total < MIN_CANDIDATES_TO_FILTER:
            return "trivial_count"
        if not window.query:
            return "empty_query"
        return None

    def _owner_screened_window(
        self,
        *,
        payload: RetrievalPayload,
        window: _GroundingCandidateWindow,
    ) -> tuple[_GroundingCandidateWindow, dict[str, Any], bool]:
        owner_screen = _apply_named_person_owner_prefilter(
            window.query,
            window.sliced_events,
            window.sliced_rels,
        )
        sliced_events, sliced_rels, total, owner_completed = self._apply_owner_screen(
            payload=payload,
            query=window.query,
            events=window.events,
            rels=window.rels,
            sliced_events=window.sliced_events,
            sliced_rels=window.sliced_rels,
            owner_screen=owner_screen,
            original_total=window.total,
        )
        return (
            _GroundingCandidateWindow(
                query=window.query,
                events=window.events,
                rels=window.rels,
                sliced_events=sliced_events,
                sliced_rels=sliced_rels,
                total=total,
            ),
            owner_screen,
            owner_completed,
        )

    def _build_logged_prompt(self, window: _GroundingCandidateWindow) -> str:
        prompt_payload = _build_unified_prompt_payload(
            window.query,
            window.sliced_events,
            window.sliced_rels,
        )
        self._log_input_detail(
            query=window.query,
            events=window.events,
            rels=window.rels,
            sliced_events=window.sliced_events,
            sliced_rels=window.sliced_rels,
            prompt_payload=prompt_payload,
        )
        return prompt_payload

    def _write_skip_trace(
        self,
        payload: RetrievalPayload,
        *,
        query: str,
        reason: str,
        input_count: int,
    ) -> None:
        skip_trace = {
            "applied": False,
            "skipped_reason": reason,
            "input_count": input_count,
        }
        payload.trace["grounding_filter"] = skip_trace
        payload.trace["grounding_filter_l2"] = dict(skip_trace)
        logger.debug(
            "Grounding filter skipped | query=%r reason=%s input_count=%d",
            _diagnostic_text(query),
            reason,
            input_count,
        )

    def _apply_owner_screen(
        self,
        *,
        payload: RetrievalPayload,
        query: str,
        events: list[dict[str, Any]],
        rels: list[dict[str, Any]],
        sliced_events: list[dict[str, Any]],
        sliced_rels: list[dict[str, Any]],
        owner_screen: dict[str, Any],
        original_total: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
        if not owner_screen["dropped_events"] and not owner_screen["dropped_relationships"]:
            return sliced_events, sliced_rels, original_total, False

        sliced_events = owner_screen["events"]
        sliced_rels = owner_screen["relationships"]
        payload.l1_events = sliced_events
        payload.l2_relationships = sliced_rels
        total_after_owner_screen = len(sliced_events) + len(sliced_rels)
        if total_after_owner_screen >= MIN_CANDIDATES_TO_FILTER:
            return sliced_events, sliced_rels, total_after_owner_screen, False

        if total_after_owner_screen == 0:
            self._write_owner_all_dropped_trace(
                payload=payload,
                query=query,
                events=events,
                rels=rels,
                owner_screen=owner_screen,
                original_total=original_total,
            )
            return sliced_events, sliced_rels, total_after_owner_screen, True

        self._write_owner_trivial_skip_trace(
            payload=payload,
            query=query,
            rels=rels,
            sliced_rels=sliced_rels,
            owner_screen=owner_screen,
            original_total=original_total,
            kept_count=total_after_owner_screen,
        )
        return sliced_events, sliced_rels, total_after_owner_screen, True

    def _write_owner_all_dropped_trace(
        self,
        *,
        payload: RetrievalPayload,
        query: str,
        events: list[dict[str, Any]],
        rels: list[dict[str, Any]],
        owner_screen: dict[str, Any],
        original_total: int,
    ) -> None:
        success_trace: dict[str, Any] = {
            "applied": True,
            "input_count": original_total,
            "input_events": len(events),
            "input_relationships": len(rels),
            "kept_events": 0,
            "kept_relationships": 0,
            "kept_count": 0,
            "elapsed_ms": 0.0,
            "why": "Named-person dialogue ownership prefilter removed mismatched evidence.",
            "all_dropped": True,
            "owner_prefilter_dropped_events": owner_screen["dropped_events"],
            "owner_prefilter_dropped_relationships": owner_screen["dropped_relationships"],
        }
        payload.trace["grounding_filter"] = success_trace
        payload.trace["grounding_filter_l2"] = {
            "applied": True,
            "input_count": len(rels),
            "kept_count": 0,
            "all_dropped": True,
        }
        logger.debug(
            "Grounding filter applied | query=%r input_events=%d "
            "input_relationships=%d kept_events=0 kept_relationships=0 "
            "why=%r all_dropped=True",
            _diagnostic_text(query),
            len(events),
            len(rels),
            _diagnostic_text(success_trace.get("why")),
        )

    def _write_owner_trivial_skip_trace(
        self,
        *,
        payload: RetrievalPayload,
        query: str,
        rels: list[dict[str, Any]],
        sliced_rels: list[dict[str, Any]],
        owner_screen: dict[str, Any],
        original_total: int,
        kept_count: int,
    ) -> None:
        skip_trace = {
            "applied": False,
            "skipped_reason": "trivial_count_after_owner_prefilter",
            "input_count": original_total,
            "kept_count": kept_count,
            "owner_prefilter_dropped_events": owner_screen["dropped_events"],
            "owner_prefilter_dropped_relationships": owner_screen["dropped_relationships"],
        }
        payload.trace["grounding_filter"] = skip_trace
        payload.trace["grounding_filter_l2"] = {
            "applied": False,
            "skipped_reason": "trivial_count_after_owner_prefilter",
            "input_count": len(rels),
            "kept_count": len(sliced_rels),
            "owner_prefilter_dropped_relationships": owner_screen["dropped_relationships"],
        }
        logger.debug(
            "Grounding filter skipped | query=%r reason=%s input_count=%d kept_count=%d",
            _diagnostic_text(query),
            skip_trace["skipped_reason"],
            original_total,
            kept_count,
        )

    def _log_input_detail(
        self,
        *,
        query: str,
        events: list[dict[str, Any]],
        rels: list[dict[str, Any]],
        sliced_events: list[dict[str, Any]],
        sliced_rels: list[dict[str, Any]],
        prompt_payload: str,
    ) -> None:
        log_detail(
            logger,
            "GROUNDING FILTER INPUT DETAIL",
            {
                "query": query,
                "input_events_total": len(events),
                "input_relationships_total": len(rels),
                "sliced_events_count": len(sliced_events),
                "sliced_relationships_count": len(sliced_rels),
                "events": event_records(sliced_events, limit=SKIP_THRESHOLD_MAX),
                "relationships": relationship_records(sliced_rels, limit=SKIP_THRESHOLD_MAX),
                "prompt_payload": prompt_payload,
            },
        )

    async def _call_grounding_llm(
        self,
        *,
        payload: RetrievalPayload,
        prompt_payload: str,
        total: int,
    ) -> tuple[Any | None, float]:
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self._bridge.chat(
                    system_prompt=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt_payload}],
                    max_tokens=512,
                    temperature=0.2,
                    disable_thinking=True,
                    json_mode=True,
                    timeout_seconds=self._timeout,
                    event_context={
                        "request_kind": "memory:grounding_filter",
                        "agent_id": "memory:hybrid_retrieval",
                    },
                ),
                timeout=self._timeout + 0.5,
            )
            return raw, (time.monotonic() - t0) * 1000
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._write_degraded_trace(
                payload, total=total, reason="llm_timeout", elapsed_ms=elapsed_ms
            )
            logger.info("Grounding filter timed out; passing raw payload through.")
            return None, elapsed_ms
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._write_degraded_trace(
                payload,
                total=total,
                reason=f"llm_exception:{type(exc).__name__}",
                elapsed_ms=elapsed_ms,
            )
            logger.warning("Grounding filter failed; passing raw payload through.", exc_info=True)
            return None, elapsed_ms

    def _write_degraded_trace(
        self,
        payload: RetrievalPayload,
        *,
        total: int,
        reason: str,
        elapsed_ms: float,
    ) -> None:
        deg = _degraded_trace(total, reason=reason, elapsed_ms=elapsed_ms)
        payload.trace["grounding_filter"] = deg
        payload.trace["grounding_filter_l2"] = _compat_l2_trace(deg)

    def _apply_llm_response(
        self,
        *,
        context: _GroundingResponseContext,
        raw: Any,
    ) -> RetrievalPayload:
        parsed = self._parsed_llm_response(
            payload=context.payload,
            query=context.query,
            raw=raw,
            elapsed_ms=context.elapsed_ms,
            event_count=len(context.sliced_events),
            total=context.total,
        )
        if parsed is None:
            return context.payload

        if not parsed.has_valid_indices:
            self._apply_no_valid_keep_result(context=context, parsed=parsed)
            return context.payload

        self._apply_valid_keep_result(context=context, parsed=parsed)
        return context.payload

    def _parsed_llm_response(
        self,
        *,
        payload: RetrievalPayload,
        query: str,
        raw: Any,
        elapsed_ms: float,
        event_count: int,
        total: int,
    ) -> _ParsedGroundingResponse | None:
        kept_indices, why = self._parse_and_log_keep_response(
            query=query,
            raw=raw,
            elapsed_ms=elapsed_ms,
        )
        if kept_indices is None:
            self._write_degraded_trace(
                payload, total=total, reason="bad_response_shape", elapsed_ms=elapsed_ms
            )
            logger.info("Grounding filter response unparseable; passing raw payload through.")
            return None
        valid_ev_indices, valid_rel_indices = _valid_keep_indices(
            kept_indices,
            event_count=event_count,
            total=total,
        )
        return _ParsedGroundingResponse(
            kept_indices=kept_indices,
            why=why,
            valid_ev_indices=valid_ev_indices,
            valid_rel_indices=valid_rel_indices,
            event_count=event_count,
        )

    def _parse_and_log_keep_response(
        self,
        *,
        query: str,
        raw: Any,
        elapsed_ms: float,
    ) -> tuple[list[int] | None, str | None]:
        kept_indices, why = _parse_keep_response(raw)
        log_detail(
            logger,
            "GROUNDING FILTER RAW OUTPUT DETAIL",
            {
                "query": query,
                "raw": raw,
                "parsed_keep": kept_indices,
                "parsed_why": why,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )
        return kept_indices, why

    def _apply_no_valid_keep_result(
        self,
        *,
        context: _GroundingResponseContext,
        parsed: _ParsedGroundingResponse,
    ) -> None:
        if not parsed.kept_indices:
            self._apply_empty_keep_result(context=context, parsed=parsed)
            return
        self._write_degraded_trace(
            context.payload,
            total=context.total,
            reason="no_valid_indices",
            elapsed_ms=context.elapsed_ms,
        )

    def _apply_empty_keep_result(
        self,
        *,
        context: _GroundingResponseContext,
        parsed: _ParsedGroundingResponse,
    ) -> None:
        payload = context.payload
        payload.l1_events = []
        payload.l2_relationships = []
        success_trace: dict[str, Any] = {
            "applied": True,
            "input_count": context.total,
            "input_events": len(context.events),
            "input_relationships": len(context.rels),
            "kept_events": 0,
            "kept_relationships": 0,
            "kept_count": 0,
            "elapsed_ms": round(context.elapsed_ms, 1),
            "why": parsed.why or None,
            "all_dropped": True,
        }
        payload.trace["grounding_filter"] = success_trace
        payload.trace["grounding_filter_l2"] = {
            "applied": True,
            "input_count": len(context.rels),
            "kept_count": 0,
            "all_dropped": True,
        }
        self._log_empty_keep_output(context, parsed, success_trace)

    def _log_empty_keep_output(
        self,
        context: _GroundingResponseContext,
        parsed: _ParsedGroundingResponse,
        success_trace: dict[str, Any],
    ) -> None:
        log_detail(
            logger,
            "GROUNDING FILTER OUTPUT DETAIL",
            {
                "query": context.query,
                "kept_indices": [],
                "dropped_event_ids": [
                    str(item.get("event_id") or "") for item in context.sliced_events
                ],
                "dropped_relationship_ids": [
                    str(item.get("triple_id") or item.get("id") or "")
                    for item in context.sliced_rels
                ],
                "why": parsed.why or None,
                "trace": success_trace,
            },
        )
        logger.info(
            "Grounding filter applied | query=%r input_events=%d "
            "input_relationships=%d kept_events=0 kept_relationships=0 "
            "why=%r all_dropped=True",
            _diagnostic_text(context.query),
            len(context.events),
            len(context.rels),
            _diagnostic_text(parsed.why or None),
        )

    def _apply_valid_keep_result(
        self,
        *,
        context: _GroundingResponseContext,
        parsed: _ParsedGroundingResponse,
    ) -> None:
        kept_events = [context.sliced_events[i - 1] for i in parsed.valid_ev_indices]
        kept_rels = [
            context.sliced_rels[i - parsed.event_count - 1]
            for i in parsed.valid_rel_indices
        ]
        context.payload.l1_events = kept_events
        context.payload.l2_relationships = kept_rels

        success_trace = self._valid_keep_trace(
            events=context.events,
            rels=context.rels,
            kept_events=kept_events,
            kept_rels=kept_rels,
            total=context.total,
            why=parsed.why,
            elapsed_ms=context.elapsed_ms,
            owner_screen=context.owner_screen,
        )
        context.payload.trace["grounding_filter"] = success_trace
        context.payload.trace["grounding_filter_l2"] = _valid_keep_l2_trace(
            context.rels,
            kept_rels,
        )
        self._log_valid_keep_output(
            query=context.query,
            kept_indices=parsed.kept_indices,
            valid_ev_indices=parsed.valid_ev_indices,
            valid_rel_indices=parsed.valid_rel_indices,
            kept_events=kept_events,
            kept_rels=kept_rels,
            sliced_events=context.sliced_events,
            sliced_rels=context.sliced_rels,
            n_ev=parsed.event_count,
            why=parsed.why,
            trace=success_trace,
        )
        self._log_valid_keep_summary(context, kept_events, kept_rels, parsed.why)

    def _log_valid_keep_summary(
        self,
        context: _GroundingResponseContext,
        kept_events: list[dict[str, Any]],
        kept_rels: list[dict[str, Any]],
        why: str | None,
    ) -> None:
        logger.info(
            "Grounding filter applied | query=%r input_events=%d input_relationships=%d "
            "kept_events=%d kept_relationships=%d why=%r",
            _diagnostic_text(context.query),
            len(context.events),
            len(context.rels),
            len(kept_events),
            len(kept_rels),
            _diagnostic_text(why or None),
        )

    def _valid_keep_trace(
        self,
        *,
        events: list[dict[str, Any]],
        rels: list[dict[str, Any]],
        kept_events: list[dict[str, Any]],
        kept_rels: list[dict[str, Any]],
        total: int,
        why: str | None,
        elapsed_ms: float,
        owner_screen: dict[str, Any],
    ) -> dict[str, Any]:
        trace: dict[str, Any] = {
            "applied": True,
            "input_count": total,
            "input_events": len(events),
            "input_relationships": len(rels),
            "kept_events": len(kept_events),
            "kept_relationships": len(kept_rels),
            "kept_count": len(kept_events) + len(kept_rels),
            "elapsed_ms": round(elapsed_ms, 1),
            "why": why or None,
        }
        if owner_screen["dropped_events"] or owner_screen["dropped_relationships"]:
            trace["owner_prefilter_dropped_events"] = owner_screen["dropped_events"]
            trace["owner_prefilter_dropped_relationships"] = owner_screen["dropped_relationships"]
        return trace

    def _log_valid_keep_output(
        self,
        *,
        query: str,
        kept_indices: list[int],
        valid_ev_indices: list[int],
        valid_rel_indices: list[int],
        kept_events: list[dict[str, Any]],
        kept_rels: list[dict[str, Any]],
        sliced_events: list[dict[str, Any]],
        sliced_rels: list[dict[str, Any]],
        n_ev: int,
        why: str | None,
        trace: dict[str, Any],
    ) -> None:
        log_detail(
            logger,
            "GROUNDING FILTER OUTPUT DETAIL",
            {
                "query": query,
                "kept_indices": kept_indices,
                "valid_event_indices": valid_ev_indices,
                "valid_relationship_indices": valid_rel_indices,
                "kept_events": event_records(kept_events, limit=SKIP_THRESHOLD_MAX),
                "kept_relationships": relationship_records(kept_rels, limit=SKIP_THRESHOLD_MAX),
                "dropped_event_ids": [
                    str(item.get("event_id") or "")
                    for index, item in enumerate(sliced_events, start=1)
                    if index not in valid_ev_indices
                ],
                "dropped_relationship_ids": [
                    str(item.get("triple_id") or item.get("id") or "")
                    for index, item in enumerate(sliced_rels, start=n_ev + 1)
                    if index not in valid_rel_indices
                ],
                "why": why or None,
                "trace": trace,
            },
        )


def _valid_keep_indices(
    kept_indices: list[int],
    *,
    event_count: int,
    total: int,
) -> tuple[list[int], list[int]]:
    valid_ev_indices = [
        index for index in kept_indices if isinstance(index, int) and 1 <= index <= event_count
    ]
    valid_rel_indices = [
        index for index in kept_indices if isinstance(index, int) and event_count < index <= total
    ]
    return valid_ev_indices, valid_rel_indices


def _valid_keep_l2_trace(
    rels: list[dict[str, Any]],
    kept_rels: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "applied": True,
        "input_count": len(rels),
        "kept_count": len(kept_rels),
    }


__all__ = ["GroundingFilter", "MIN_CANDIDATES_TO_FILTER", "SKIP_THRESHOLD_MAX"]
