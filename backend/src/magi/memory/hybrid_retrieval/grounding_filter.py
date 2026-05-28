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
    JSON, no bridge wired up, candidates list too short to bother)
    degrades silently to "no filtering" — the raw payload flows
    through unchanged.

  - We only filter ``l1_events``. L2 layers (relationships /
    assertions / episodes) are already small and structurally
    grounded; the user's pain point is L1 noise.

  - The model call uses ``IntentDecider``-style cheap LLM (qwen-flash
    or similar) injected by the caller. The grounding pass is short
    (sub-3s), takes minimal tokens (compact candidate summaries).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Iterable

from .models import RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)

# Below this candidate count, skip the LLM entirely — filtering 3
# events isn't worth the latency.
SKIP_THRESHOLD = 10

# Hard cap on what we'll show the grounding LLM. If retrieval somehow
# delivers 500 candidates, we trim to top SKIP_THRESHOLD_MAX by
# original rank (the head of the RRF-fused list); the trimmed tail
# never had a real chance of being scored by the answer LLM anyway.
SKIP_THRESHOLD_MAX = 60

# Per-candidate content snippet length fed into the prompt. Tight —
# we want intent matching, not full-text grounding.
CONTENT_SNIPPET_CHARS = 80


_SYSTEM_PROMPT = """\
You are a relevance filter for a personal memory retrieval system.

You receive (1) a user's natural-language query and (2) a numbered list
of candidate memory events. Your job is to keep ONLY the candidates
that genuinely help answer THAT query. Drop unrelated noise.

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
"""


class GroundingFilter:
    """Apply an LLM-as-listwise-filter to RetrievalPayload.l1_events.

    Instantiated once at service setup; ``apply()`` is the per-query
    entry point. Stateless apart from the LLM bridge handle and the
    timeout knob.
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
        """Filter ``payload.l1_events`` in place, return the same payload.

        Records trace fields:
          - ``grounding_filter.applied`` (bool)
          - ``grounding_filter.input_count`` (int)
          - ``grounding_filter.kept_count`` (int)
          - ``grounding_filter.elapsed_ms`` (float)
          - ``grounding_filter.why`` (str | None)
          - ``grounding_filter.degraded_reason`` (str | None) — set on
            failure path; payload still returned unchanged.
        """
        if not self._enabled:
            return payload
        events = payload.l1_events or []
        if len(events) < SKIP_THRESHOLD:
            # Too few candidates to justify the LLM round-trip.
            payload.trace["grounding_filter"] = {
                "applied": False,
                "skipped_reason": "below_threshold",
                "input_count": len(events),
            }
            return payload

        query = str(request.query or "").strip()
        if not query:
            payload.trace["grounding_filter"] = {
                "applied": False,
                "skipped_reason": "empty_query",
                "input_count": len(events),
            }
            return payload

        sliced = events[:SKIP_THRESHOLD_MAX]
        prompt_payload = _build_prompt_payload(query, sliced)
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
            payload.trace["grounding_filter"] = _degraded_trace(
                len(events), reason="llm_timeout", elapsed_ms=(time.monotonic() - t0) * 1000
            )
            logger.info("Grounding filter timed out; passing raw payload through.")
            return payload
        except Exception as exc:  # noqa: BLE001
            payload.trace["grounding_filter"] = _degraded_trace(
                len(events),
                reason=f"llm_exception:{type(exc).__name__}",
                elapsed_ms=(time.monotonic() - t0) * 1000,
            )
            logger.warning("Grounding filter failed; passing raw payload through.", exc_info=True)
            return payload

        elapsed_ms = (time.monotonic() - t0) * 1000
        kept_indices, why = _parse_keep_response(raw)
        if kept_indices is None:
            payload.trace["grounding_filter"] = _degraded_trace(
                len(events), reason="bad_response_shape", elapsed_ms=elapsed_ms
            )
            logger.info("Grounding filter response unparseable; passing raw payload through.")
            return payload

        # Translate 1-based indices into actual events. Out-of-range
        # indices are silently dropped (LLMs sometimes hallucinate
        # indices past the list end).
        kept_events = [
            sliced[i - 1] for i in kept_indices if isinstance(i, int) and 1 <= i <= len(sliced)
        ]
        # If the LLM keeps zero candidates, treat that as "filter was
        # too aggressive" and fall back to raw — better to give the
        # answer LLM noisy context than nothing at all.
        if not kept_events:
            payload.trace["grounding_filter"] = {
                "applied": False,
                "skipped_reason": "empty_keep_set",
                "input_count": len(events),
                "elapsed_ms": round(elapsed_ms, 1),
                "why": why or None,
            }
            return payload

        payload.l1_events = kept_events
        payload.trace["grounding_filter"] = {
            "applied": True,
            "input_count": len(events),
            "kept_count": len(kept_events),
            "elapsed_ms": round(elapsed_ms, 1),
            "why": why or None,
        }
        return payload


# ---------- helpers ----------


def _build_prompt_payload(query: str, events: list[dict[str, Any]]) -> str:
    """Construct the user-message JSON we feed to the filter LLM.

    Each event reduces to ``{idx, source, when, snippet}`` — just
    enough for an intent-match decision. We intentionally do NOT pass
    the whole content / metadata blob; tokens add up fast and the LLM
    here is a filter, not an answerer.
    """
    candidates: list[dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        snippet = str(event.get("content") or "")
        if len(snippet) > CONTENT_SNIPPET_CHARS:
            snippet = snippet[:CONTENT_SNIPPET_CHARS].rstrip() + "…"
        snippet = snippet.replace("\n", " ")
        when_ts = event.get("timestamp") or event.get("occurred_at")
        candidates.append(
            {
                "idx": i,
                "source": str(event.get("source") or "unknown"),
                "when": _format_when(when_ts),
                "snippet": snippet,
            }
        )
    body = {"query": query, "candidates": candidates}
    return json.dumps(body, ensure_ascii=False)


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


__all__ = ["GroundingFilter", "SKIP_THRESHOLD", "SKIP_THRESHOLD_MAX"]
