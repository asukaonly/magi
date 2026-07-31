"""LLM-based query expansion for improved retrieval recall."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from magi.utils.diagnostic_logging import full_content_logging_enabled

logger = logging.getLogger(__name__)

_EXPANSION_SYSTEM_PROMPT = """\
You are a query expansion assistant for a personal memory retrieval system.

⚠️ CRITICAL LANGUAGE RULE (this overrides everything else):
   ALL expansions MUST be in the SAME language and script as the user's
   original query. Never translate. The user's memories are indexed in the
   language they were recorded in — a Chinese OCR or Chinese chat will not
   match an English keyword, and vice versa. If the original is Chinese,
   every expansion is Chinese. If English, every expansion is English. If
   Japanese, every expansion is Japanese. No mixing, no "let's also try
   English just in case".

The user's memories live in heterogeneous stores — past conversations,
screen-capture OCR text, browser history titles, calendar events, etc.
A single record may cover multiple unrelated topics, so the relevant
detail is often mentioned incidentally inside a record about something
else.

Given the user's query, generate {max_expansions} alternative search queries that target
DIFFERENT sub-concepts or concrete entities the user likely mentioned,
so each query can independently retrieve a different relevant record.

Strategy:
1. Decompose — break the question into distinct sub-concepts, concrete
   nouns, or specific entities the user would have written / typed / had
   on screen.
2. Diversify — each query uses substantially different keywords so they
   hit different records (NOT just synonym rewordings of the same phrase).
3. Be concrete — prefer specific object names, activity verbs, or proper
   nouns over abstract category words.

Examples (notice every pair stays in its source language — that is the
single most important pattern below):

  English query: "How many musical instruments do I own?"
  → ["guitar playing practice", "piano keyboard lessons"]

  English query: "Can you recommend a show or movie for me tonight?"
  → ["favorite TV series binge watching", "comedy Netflix recommendation"]

  中文 query: "我最近在 chrome 里看什么书评网站"
  → ["豆瓣 短评 书", "书评 推荐 网页"]

  中文 query: "刚刚在群里看到的那只猫是什么梗"
  → ["猫 睡觉 摇醒 表情包", "群聊 猫 出处"]

  中文 query: "上周和小明聊到的那个项目"
  → ["小明 项目 进展", "讨论 计划 上周"]

  日本語 query: "今日のミーティングで何を話した"
  → ["会議 議事録 決定", "同僚 議論 今日"]

Return a JSON array of exactly {max_expansions} strings. Output ONLY the JSON array.
Rules:
- Each query is concise (3-8 tokens; Chinese 2-6 字 is fine)
- Do NOT repeat or paraphrase the original query verbatim
- ALL queries MUST be in the same language/script as the original — see
  the language rule at the top; this is non-negotiable
"""


class QueryExpander:
    """Generate alternative query formulations via LLM for broader recall."""

    def __init__(
        self,
        llm_bridge: Any,
        *,
        timeout_seconds: float = 3.0,
        max_expansions: int = 2,
    ) -> None:
        self._bridge = llm_bridge
        self._timeout = timeout_seconds
        self._max_expansions = max(1, min(5, int(max_expansions)))

    async def expand(self, query: str) -> list[str]:
        """Generate expanded queries. Returns empty list on failure.

        The original query is NOT included in the returned list.
        """
        if not self._bridge:
            return []

        t0 = time.monotonic()
        try:
            raw = await self._bridge.chat(
                system_prompt=_EXPANSION_SYSTEM_PROMPT.format(
                    max_expansions=self._max_expansions,
                ),
                messages=[{"role": "user", "content": query}],
                max_tokens=256,
                temperature=0.7,
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=self._timeout,
                event_context={
                    "request_kind": "memory:hybrid_query_expansion",
                    "agent_id": "memory:hybrid_retrieval",
                },
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "Query expansion completed elapsed_ms=%.1f query_len=%d",
                elapsed_ms, len(query),
            )
            expansions = self._parse(raw, max_expansions=self._max_expansions)
            # Belt-and-braces: even with the prompt's same-language rule
            # the LLM occasionally translates anyway. The user's memories
            # are indexed in the language they were recorded in, so
            # translated expansions match nothing (or worse — they match
            # incidental Latin tokens like URLs / brand names in
            # otherwise-Chinese content and skew ranking). Drop any
            # expansion whose script class differs from the original.
            return _drop_cross_script_expansions(query, expansions)
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "Query expansion failed elapsed_ms=%.1f query=%r",
                elapsed_ms,
                query[:100] if full_content_logging_enabled() else "[content omitted]",
                exc_info=True,
            )
            return []

    @staticmethod
    def _parse(raw: str, *, max_expansions: int = 2) -> list[str]:
        """Parse the LLM response into a list of query strings."""
        text = raw.strip()
        # Try to extract JSON array from the response.
        # LLM output may contain multiple bracket pairs (e.g. explanation
        # text around the array).  We try progressively narrower substrings
        # to find the first valid JSON array.
        start = text.find("[")
        if start == -1:
            logger.warning(
                "Query expansion response has no JSON array: %r",
                (
                    text[:200]
                    if full_content_logging_enabled()
                    else f"[content omitted; chars={len(text)}]"
                ),
            )
            return []

        parsed = None
        search_from = len(text)
        while search_from > start:
            end = text.rfind("]", start, search_from)
            if end == -1:
                break
            try:
                candidate = json.loads(text[start:end + 1])
                if isinstance(candidate, list):
                    parsed = candidate
                    break
            except json.JSONDecodeError:
                pass
            search_from = end

        if parsed is None:
            logger.warning(
                "Query expansion response is not valid JSON: %r",
                (
                    text[:200]
                    if full_content_logging_enabled()
                    else f"[content omitted; chars={len(text)}]"
                ),
            )
            return []
        result = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result[:max(1, min(5, int(max_expansions)))]


# --------- script-class detection for cross-language drop ---------


def _has_cjk(text: str) -> bool:
    """True iff ``text`` contains any Han / Hiragana / Katakana / Hangul
    character. Used as a coarse "is this CJK content" signal.

    Block ranges:
      CJK Unified Ideographs       U+4E00..U+9FFF
      CJK Ext A                    U+3400..U+4DBF
      CJK Compatibility            U+F900..U+FAFF
      Hiragana                     U+3040..U+309F
      Katakana                     U+30A0..U+30FF
      Hangul Syllables             U+AC00..U+D7AF
    """
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF
            or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF
            or 0x3040 <= cp <= 0x309F
            or 0x30A0 <= cp <= 0x30FF
            or 0xAC00 <= cp <= 0xD7AF
        ):
            return True
    return False


def _drop_cross_script_expansions(query: str, expansions: list[str]) -> list[str]:
    """Drop expansions whose script class doesn't match the original.

    Specifically: if the original has any CJK character, drop expansions
    that contain ZERO CJK characters (treated as accidental translation
    into ASCII). Symmetric check for ASCII-origin queries.

    Conservative: a mixed expansion (some CJK + some Latin) is KEPT,
    because real queries about products / URLs / code names often mix
    scripts intentionally (e.g. "claude 截图 ocr"). We only filter the
    obvious all-translated-to-other-script case.
    """
    if not expansions:
        return expansions
    original_has_cjk = _has_cjk(query)
    kept: list[str] = []
    dropped: list[str] = []
    for expansion in expansions:
        expansion_has_cjk = _has_cjk(expansion)
        if original_has_cjk and not expansion_has_cjk:
            dropped.append(expansion)
            continue
        if (not original_has_cjk) and expansion_has_cjk:
            # ASCII-origin query expanded into CJK — symmetric reject.
            # User's English-language data won't be indexed under CJK
            # tokens; this would be a bad expansion the same way.
            dropped.append(expansion)
            continue
        kept.append(expansion)
    if dropped:
        logger.info(
            "Query expansion dropped cross-script entries kept=%d dropped=%d",
            len(kept), len(dropped),
        )
    return kept
