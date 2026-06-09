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
    JSON, no bridge wired up, candidates too trivial to compare (0 or 1 events))
    degrades silently to "no filtering" — the raw payload flows
    through unchanged.

  - We only filter ``l1_events``. L2 layers (relationships /
    assertions / episodes) are already small and structurally
    grounded; the user's pain point is L1 noise.

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
from typing import Any, Iterable

from .models import RetrievalPayload, RetrievalQuery

logger = logging.getLogger(__name__)

# Minimum candidate count worth an LLM round-trip. A single candidate has
# nothing to filter against; 2+ can carry noise. NOTE: low-recall sets are
# the MOST important to filter (few hits, often all noise), so unlike the
# previous design we do NOT skip moderate counts — only the trivial 0/1 case.
MIN_CANDIDATES_TO_FILTER = 2

# Hard cap on what we'll show the grounding LLM. If retrieval somehow
# delivers 500 candidates, we trim to top SKIP_THRESHOLD_MAX by
# original rank (the head of the RRF-fused list); the trimmed tail
# never had a real chance of being scored by the answer LLM anyway.
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

Two worked examples (notice each rationale stays in the source
language, and unrelated-but-superficially-matching candidates are
dropped):

Example 1 — Chinese query:
Input:
{"query": "我之前在 chrome 看的那个 cat 表情包梗图来着，叫什么熬醒的",
 "candidates": [
   {"idx": 1, "source": "screenshot_timeline", "when": "2026-05-28 15:05",
    "content": "屏幕快照时间线 屏幕截图 黎月风 上次猫熬我，我就请假熬了它三天，睡着就摇醒…"},
   {"idx": 2, "source": "chrome_history", "when": "2026-05-28 11:20",
    "content": "Chrome 浏览 GitHub - some-unrelated/repo PR #42"},
   {"idx": 3, "source": "chat_projector", "when": "2026-05-28 15:01",
    "content": "叫我子涵"},
   {"idx": 4, "source": "screenshot_timeline", "when": "2026-05-28 15:13",
    "content": "屏幕快照时间线 屏幕截图 VSCode magi/插件改造 grounding_filter.py"}
 ]}
Output:
{"keep": [1], "why": "只有 1 是包含猫熬人梗图 OCR 的截图；2 是无关 PR、3 是无关聊天、4 是 IDE 截图。"}

Example 2 — English query:
Input:
{"query": "what was that Tailscale config page I had open yesterday",
 "candidates": [
   {"idx": 1, "source": "chrome_history", "when": "2026-05-27 22:14",
    "content": "Chrome browse Tailscale - Subnet routers and traffic relay nodes"},
   {"idx": 2, "source": "chrome_history", "when": "2026-05-27 22:18",
    "content": "Chrome browse Hacker News - Show HN: a side project"},
   {"idx": 3, "source": "screenshot_timeline", "when": "2026-05-27 22:15",
    "content": "Screenshot Timeline Screen Capture Chrome - Tailscale admin console MagicDNS settings page"},
   {"idx": 4, "source": "chat_projector", "when": "2026-05-27 23:01",
    "content": "讨论了 K8s 集群规划"}
 ]}
Output:
{"keep": [1, 3], "why": "1 and 3 are both Tailscale pages from yesterday; 2 is HN and 4 is K8s chat."}
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
        if len(events) < MIN_CANDIDATES_TO_FILTER:
            payload.trace["grounding_filter"] = {
                "applied": False,
                "skipped_reason": "trivial_count",
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
        if not kept_events:
            if not kept_indices:
                # LLM explicitly returned an empty keep set — a VALID
                # "none of these are relevant" verdict. Trust it and drop all
                # L1 events. (Timeout / exception / unparseable already fell
                # back above — those are failures. An explicit empty verdict is
                # a real judgment, so we must NOT silently restore the noise.)
                payload.l1_events = []
                payload.trace["grounding_filter"] = {
                    "applied": True,
                    "input_count": len(events),
                    "kept_count": 0,
                    "elapsed_ms": round(elapsed_ms, 1),
                    "why": why or None,
                    "all_dropped": True,
                }
                return payload
            # kept_indices was non-empty but every index was out of range —
            # the LLM hallucinated indices rather than giving a clean verdict.
            # Treat as degraded and fall back to raw.
            payload.trace["grounding_filter"] = _degraded_trace(
                len(events), reason="no_valid_indices", elapsed_ms=elapsed_ms
            )
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

    Each event carries its full ``content`` field (capped only by
    CONTENT_CAP_CHARS as a defensive net against pathological 100KB+
    rows). The filter LLM MUST see the same textual content the
    answer LLM downstream will see — anything less risks the filter
    dropping a candidate whose key signal lives past the cap, leaving
    the answer LLM with no candidate that could have matched.
    """
    candidates: list[dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        content = str(event.get("content") or "")
        if len(content) > CONTENT_CAP_CHARS:
            # Pathological-input guard. In normal use real OCR /
            # chat events are well under this cap.
            content = content[:CONTENT_CAP_CHARS].rstrip() + "…[truncated]"
        # Newlines preserved — the model can read a chunk of OCR as
        # naturally as it would in the answer-LLM prompt. We don't
        # collapse to a single line because OCR layout cues (line
        # breaks) genuinely help relevance judgement.
        when_ts = event.get("timestamp") or event.get("occurred_at")
        candidates.append(
            {
                "idx": i,
                "source": str(event.get("source") or "unknown"),
                "when": _format_when(when_ts),
                "content": content,
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


__all__ = ["GroundingFilter", "MIN_CANDIDATES_TO_FILTER", "SKIP_THRESHOLD_MAX"]
