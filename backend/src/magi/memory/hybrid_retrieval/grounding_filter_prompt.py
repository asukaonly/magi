"""Prompt construction and response parsing for the grounding filter."""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from magi.memory.dialogue_transcripts import extract_dialogue_speaker

from .grounding_filter_owner import extract_query_named_people

CONTENT_CAP_CHARS = 4000

SYSTEM_PROMPT = """\
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
  - If a query asks about a named person, keep a candidate only when it
    is about that same named person, directly mentions that person, or
    clearly supports answering about that person's situation. Do not keep
    a candidate merely because another participant has a similar fact.
    For dialogue events, check the `speaker` field and quoted first-person
    statements: "Melanie said, I bought shoes" is about Melanie, not
    Caroline.

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


def build_unified_prompt_payload(
    query: str,
    events: list[dict[str, Any]],
    rels: list[dict[str, Any]],
) -> str:
    """Build the user-message JSON for the unified grounding filter."""
    candidates: list[dict[str, Any]] = []
    query_named_people = extract_query_named_people(query)
    for i, event in enumerate(events, start=1):
        content = str(event.get("content") or "")
        if len(content) > CONTENT_CAP_CHARS:
            content = content[:CONTENT_CAP_CHARS].rstrip() + "…[truncated]"
        when_ts = event.get("timestamp") or event.get("occurred_at")
        candidate = {
            "idx": i,
            "type": "event",
            "source": str(event.get("source") or "unknown"),
            "when": format_when(when_ts),
            "content": content,
        }
        speaker = extract_dialogue_speaker(content)
        if speaker:
            candidate["speaker"] = speaker
        candidates.append(candidate)

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
        candidate = {
            "idx": offset + j,
            "type": "relationship",
            "predicate": str(rel.get("predicate") or ""),
            "statement": natural,
        }
        for key in ("subject_id", "subject_name", "object_id", "object_name"):
            value = str(rel.get(key) or "").strip()
            if value:
                candidate[key] = value
        candidates.append(candidate)

    body: dict[str, Any] = {"query": query}
    if query_named_people:
        body["query_named_people"] = query_named_people
    body["candidates"] = candidates
    return json.dumps(body, ensure_ascii=False)


def build_prompt_payload(query: str, events: list[dict[str, Any]]) -> str:
    """Build a prompt payload for L1 events only."""
    return build_unified_prompt_payload(query, events, [])


def build_l2_prompt_payload(query: str, rels: list[dict[str, Any]]) -> str:
    """Build a prompt payload for L2 relationships only."""
    return build_unified_prompt_payload(query, [], rels)


def format_when(ts: Any) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        return _dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return None


def parse_keep_response(raw: Any) -> tuple[list[int] | None, str | None]:
    """Extract (keep_indices, why) from the LLM's JSON response."""
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


__all__ = [
    "CONTENT_CAP_CHARS",
    "SYSTEM_PROMPT",
    "build_l2_prompt_payload",
    "build_prompt_payload",
    "build_unified_prompt_payload",
    "format_when",
    "parse_keep_response",
]
