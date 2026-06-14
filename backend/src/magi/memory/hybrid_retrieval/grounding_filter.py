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
import json
import logging
import time
from typing import Any

from .models import RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)

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

# Per-candidate content cap. The grounding LLM MUST see the same
# textual content as the answer LLM downstream — otherwise it can
# silently drop a candidate whose key signal lives past the cap, and
# the user gets "I couldn't find anything" for a record that was
# actually retrieved. An earlier version of this filter capped at 80
# chars which caused exactly that failure mode on real OCR content
# (the "猫熬我" passage starts ~200 chars into the screenshot text).
#
# The cap here is a safety net against pathological inputs only
# (e.g. a single L1 row with 100KB of OCR text would explode the
# prompt). Set well above the 95th percentile of real fact_events.content
# lengths so it's effectively "give the LLM everything" in normal use.
CONTENT_CAP_CHARS = 4000


_SYSTEM_PROMPT = """\
You are a relevance filter for a personal memory retrieval system.

You receive (1) a user's natural-language query and (2) a numbered list
of candidate items. Items are one of two types:
  - type "event"        — a memory event (browsing, screenshot OCR, chat…)
  - type "relationship" — a knowledge-graph relationship statement

Your job is to keep ONLY the candidates that genuinely help answer THAT
query. Drop unrelated noise, regardless of item type.

Reply with a single JSON object:

  {"keep": [<idx>, <idx>, ...], "why": "<one short sentence>"}

Rules:
  - `keep` is a list of integers — the 1-based indices of candidates to
    keep, in original order.
  - Be strict but not destructive: if you genuinely can't tell, KEEP it.
    The answer LLM downstream can re-read; bias toward recall over
    precision.
  - Reply in the same language as the query (Chinese in / Chinese out).
  - `why` is a one-sentence rationale; the user may see it as a UI hint.
  - Output ONLY the JSON object. No prose before or after.

Two worked examples (notice each rationale stays in the source
language, and unrelated-but-superficially-matching candidates are
dropped):

Example 1 — Chinese query, mixed events + relationships:
Input:
{"query": "我同事的老板是谁",
 "candidates": [
   {"idx": 1, "type": "relationship", "predicate": "REPORTS_TO",
    "statement": "用户的同事 王明 向 陈总 汇报"},
   {"idx": 2, "type": "relationship", "predicate": "LIKES",
    "statement": "用户喜欢听周杰伦的歌"},
   {"idx": 3, "type": "event", "source": "chat_projector",
    "when": "2026-05-28 09:00",
    "content": "讨论了 K8s 集群规划"},
   {"idx": 4, "type": "relationship", "predicate": "USES",
    "statement": "用户使用 yacd 管理代理规则"}
 ]}
Output:
{"keep": [1], "why": "只有 1 描述了同事的汇报关系（即老板关系），2/3/4 均与查询无关。"}

Example 2 — English query, events only:
Input:
{"query": "what was that Tailscale config page I had open yesterday",
 "candidates": [
   {"idx": 1, "type": "event", "source": "chrome_history",
    "when": "2026-05-27 22:14",
    "content": "Chrome browse Tailscale - Subnet routers and traffic relay nodes"},
   {"idx": 2, "type": "event", "source": "chrome_history",
    "when": "2026-05-27 22:18",
    "content": "Chrome browse Hacker News - Show HN: a side project"},
   {"idx": 3, "type": "event", "source": "screenshot_timeline",
    "when": "2026-05-27 22:15",
    "content": "Screenshot Timeline Screen Capture Chrome - Tailscale admin console MagicDNS settings page"},
   {"idx": 4, "type": "event", "source": "chat_projector",
    "when": "2026-05-27 23:01",
    "content": "讨论了 K8s 集群规划"}
 ]}
Output:
{"keep": [1, 3], "why": "1 and 3 are both Tailscale pages from yesterday; 2 is HN and 4 is K8s chat."}
"""


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
        """Filter ``payload.l1_events`` and ``payload.l2_relationships``
        in place with a SINGLE LLM call, return the same payload.

        Degrades silently to pass-through on any failure path, leaving
        BOTH lists unchanged.

        Records trace fields under ``grounding_filter``:
          - ``applied`` (bool)
          - ``input_count`` (int) — total combined candidates shown to LLM
          - ``input_events`` (int) — L1 events portion
          - ``input_relationships`` (int) — L2 relationships portion
          - ``kept_events`` (int) — on success
          - ``kept_relationships`` (int) — on success
          - ``kept_count`` (int) — total kept, on success
          - ``elapsed_ms`` (float)
          - ``why`` (str | None)
          - ``degraded_reason`` (str | None) — set on failure path.

        Also writes a minimal ``grounding_filter_l2`` alias for
        backward compatibility:
          - ``applied`` (bool)
          - ``input_count`` (int)
          - ``kept_count`` (int) — on success
          - ``degraded_reason`` (str) — on failure
        """
        if not self._enabled:
            return payload

        query = str(request.query or "").strip()

        events = payload.l1_events or []
        rels = payload.l2_relationships or []
        sliced_events = events[:SKIP_THRESHOLD_MAX]
        sliced_rels = rels[:SKIP_THRESHOLD_MAX]
        total = len(sliced_events) + len(sliced_rels)

        if total < MIN_CANDIDATES_TO_FILTER:
            # Write the same skip trace on both keys so downstream
            # readers that check either key behave consistently.
            skip_trace = {
                "applied": False,
                "skipped_reason": "trivial_count",
                "input_count": total,
            }
            payload.trace["grounding_filter"] = skip_trace
            payload.trace["grounding_filter_l2"] = dict(skip_trace)
            return payload

        if not query:
            skip_trace = {
                "applied": False,
                "skipped_reason": "empty_query",
                "input_count": total,
            }
            payload.trace["grounding_filter"] = skip_trace
            payload.trace["grounding_filter_l2"] = dict(skip_trace)
            return payload

        prompt_payload = _build_unified_prompt_payload(query, sliced_events, sliced_rels)
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
                timeout=self._timeout + 0.5,  # outer wait_for as belt+braces
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - t0) * 1000
            deg = _degraded_trace(total, reason="llm_timeout", elapsed_ms=elapsed_ms)
            payload.trace["grounding_filter"] = deg
            payload.trace["grounding_filter_l2"] = _compat_l2_trace(deg)
            logger.info("Grounding filter timed out; passing raw payload through.")
            return payload
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.monotonic() - t0) * 1000
            deg = _degraded_trace(
                total,
                reason=f"llm_exception:{type(exc).__name__}",
                elapsed_ms=elapsed_ms,
            )
            payload.trace["grounding_filter"] = deg
            payload.trace["grounding_filter_l2"] = _compat_l2_trace(deg)
            logger.warning("Grounding filter failed; passing raw payload through.", exc_info=True)
            return payload

        elapsed_ms = (time.monotonic() - t0) * 1000
        kept_indices, why = _parse_keep_response(raw)
        if kept_indices is None:
            deg = _degraded_trace(total, reason="bad_response_shape", elapsed_ms=elapsed_ms)
            payload.trace["grounding_filter"] = deg
            payload.trace["grounding_filter_l2"] = _compat_l2_trace(deg)
            logger.info("Grounding filter response unparseable; passing raw payload through.")
            return payload

        # Global indices are 1-based, laid out as:
        #   1 .. len(sliced_events)        → events
        #   len(sliced_events)+1 .. total  → relationships
        n_ev = len(sliced_events)
        valid_ev_indices = [i for i in kept_indices if isinstance(i, int) and 1 <= i <= n_ev]
        valid_rel_indices = [
            i for i in kept_indices if isinstance(i, int) and n_ev < i <= total
        ]

        all_valid_count = len(valid_ev_indices) + len(valid_rel_indices)

        if all_valid_count == 0:
            if not kept_indices:
                # LLM explicitly returned an empty keep set — a VALID
                # "none of these are relevant" verdict. Trust it and
                # clear BOTH lists.
                payload.l1_events = []
                payload.l2_relationships = []
                success_trace: dict[str, Any] = {
                    "applied": True,
                    "input_count": total,
                    "input_events": len(events),
                    "input_relationships": len(rels),
                    "kept_events": 0,
                    "kept_relationships": 0,
                    "kept_count": 0,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "why": why or None,
                    "all_dropped": True,
                }
                payload.trace["grounding_filter"] = success_trace
                payload.trace["grounding_filter_l2"] = {
                    "applied": True,
                    "input_count": len(rels),
                    "kept_count": 0,
                    "all_dropped": True,
                }
                return payload

            # kept_indices was non-empty but every index was out of range
            # (LLM hallucinated indices). Treat as degraded.
            deg = _degraded_trace(total, reason="no_valid_indices", elapsed_ms=elapsed_ms)
            payload.trace["grounding_filter"] = deg
            payload.trace["grounding_filter_l2"] = _compat_l2_trace(deg)
            return payload

        # At least one valid index: apply the filter.
        kept_events = [sliced_events[i - 1] for i in valid_ev_indices]
        kept_rels = [sliced_rels[i - n_ev - 1] for i in valid_rel_indices]

        payload.l1_events = kept_events
        payload.l2_relationships = kept_rels

        payload.trace["grounding_filter"] = {
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
        payload.trace["grounding_filter_l2"] = {
            "applied": True,
            "input_count": len(rels),
            "kept_count": len(kept_rels),
        }
        return payload


# ---------- helpers ----------


def _build_unified_prompt_payload(
    query: str,
    events: list[dict[str, Any]],
    rels: list[dict[str, Any]],
) -> str:
    """Build the user-message JSON for the unified grounding filter.

    Events occupy global indices 1 .. len(events); relationships follow
    at len(events)+1 .. len(events)+len(rels). Each candidate carries a
    ``type`` field so the LLM can apply type-appropriate reasoning.
    """
    candidates: list[dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        content = str(event.get("content") or "")
        if len(content) > CONTENT_CAP_CHARS:
            content = content[:CONTENT_CAP_CHARS].rstrip() + "…[truncated]"
        when_ts = event.get("timestamp") or event.get("occurred_at")
        candidates.append(
            {
                "idx": i,
                "type": "event",
                "source": str(event.get("source") or "unknown"),
                "when": _format_when(when_ts),
                "content": content,
            }
        )

    offset = len(events)
    for j, rel in enumerate(rels, start=1):
        natural = str(rel.get("natural_summary") or "").strip()
        if not natural:
            subj = rel.get("subject_name") or rel.get("subject_id") or ""
            pred = rel.get("predicate") or ""
            obj = rel.get("object_name") or rel.get("object_id") or ""
            natural = f"{subj} --{pred}--> {obj}"
        if len(natural) > CONTENT_CAP_CHARS:
            natural = natural[:CONTENT_CAP_CHARS].rstrip() + "…[truncated]"
        candidates.append(
            {
                "idx": offset + j,
                "type": "relationship",
                "predicate": str(rel.get("predicate") or ""),
                "statement": natural,
            }
        )

    body = {"query": query, "candidates": candidates}
    return json.dumps(body, ensure_ascii=False)


# Keep the old prompt-builder helpers around so any callers that import
# them directly (e.g. tests that unit-test prompt shape) don't break.
def _build_prompt_payload(query: str, events: list[dict[str, Any]]) -> str:
    """Build a prompt payload for L1 events only (kept for backward compat / tests)."""
    return _build_unified_prompt_payload(query, events, [])


def _build_l2_prompt_payload(query: str, rels: list[dict[str, Any]]) -> str:
    """Build a prompt payload for L2 relationships only (kept for backward compat / tests)."""
    return _build_unified_prompt_payload(query, [], rels)


def _format_when(ts: Any) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return None


def _parse_keep_response(raw: Any) -> tuple[list[int] | None, str | None]:
    """Extract (keep_indices, why) from the LLM's JSON response.

    Returns (None, None) on any parse failure; caller treats that as
    degraded-pass-through. Tolerant of common LLM output shapes:
      - the raw text may be JSON, or JSON wrapped in prose
      - integers may arrive as strings ("3" instead of 3)
    """
    text = raw if isinstance(raw, str) else (raw.get("content") if isinstance(raw, dict) else None)
    if not text or not isinstance(text, str):
        return None, None
    text = text.strip()

    start = text.find("{")
    if start == -1:
        return None, None
    parsed: Any = None
    search_from = len(text)
    while search_from > start:
        end = text.rfind("}", start, search_from)
        if end == -1:
            break
        try:
            candidate = json.loads(text[start: end + 1])
            if isinstance(candidate, dict):
                parsed = candidate
                break
        except json.JSONDecodeError:
            pass
        search_from = end
    if parsed is None:
        return None, None

    raw_keep = parsed.get("keep")
    if not isinstance(raw_keep, list):
        return None, None
    keep: list[int] = []
    for item in raw_keep:
        if isinstance(item, bool):
            # bool is a subclass of int in Python; skip explicitly.
            continue
        if isinstance(item, int):
            keep.append(item)
        elif isinstance(item, str):
            stripped = item.strip()
            if stripped.isdigit():
                keep.append(int(stripped))
    why = parsed.get("why")
    why_text = str(why).strip() if isinstance(why, str) else None
    return keep, why_text


def _degraded_trace(input_count: int, *, reason: str, elapsed_ms: float) -> dict[str, Any]:
    return {
        "applied": False,
        "degraded_reason": reason,
        "input_count": input_count,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _compat_l2_trace(main_trace: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal grounding_filter_l2 alias from the main degraded trace."""
    result: dict[str, Any] = {"applied": False}
    if "input_count" in main_trace:
        result["input_count"] = main_trace["input_count"]
    if "degraded_reason" in main_trace:
        result["degraded_reason"] = main_trace["degraded_reason"]
    if "elapsed_ms" in main_trace:
        result["elapsed_ms"] = main_trace["elapsed_ms"]
    return result


__all__ = ["GroundingFilter", "MIN_CANDIDATES_TO_FILTER", "SKIP_THRESHOLD_MAX"]
