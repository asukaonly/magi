"""LLM-based query expansion for improved retrieval recall."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_EXPANSION_SYSTEM_PROMPT = """\
You are a query expansion assistant for a personal memory retrieval system.
The user's memories are stored as past conversations. A single conversation may \
cover MULTIPLE unrelated topics, so the relevant fact is often mentioned \
incidentally inside a conversation about something else.

Given a user's memory query, generate 2 alternative search queries that target \
DIFFERENT sub-concepts or concrete entities the user likely mentioned, so each \
query can independently retrieve a different relevant conversation.

Strategy:
1. Decompose: break the question into distinct sub-concepts, concrete nouns, \
   or specific entities the user would have mentioned in everyday conversation.
2. Diversify: each query should use substantially different keywords so they \
   hit different conversations—NOT just synonym rewording of the same phrase.
3. Be concrete: prefer specific object names, activity verbs, or proper nouns \
   over abstract category words.

Examples:
  "How many musical instruments do I own?"
  → ["guitar playing practice", "piano keyboard lessons"]

  "How many siblings do I have?"
  → ["sister family growing up", "brother family"]

  "How many hours driving to road trip destinations?"
  → ["drove hours trip destination", "road trip car travel time"]

  "Can you recommend a show or movie for me tonight?"
  → ["favorite TV series binge watching", "comedy special Netflix recommendation"]

Return a JSON array of exactly 2 strings. Output ONLY the JSON array.
Rules:
- Each query should be concise (3-8 words)
- Do NOT repeat or paraphrase the original query
- Queries should be in the same language as the original
"""


class QueryExpander:
    """Generate alternative query formulations via LLM for broader recall."""

    def __init__(
        self,
        llm_bridge: Any,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._bridge = llm_bridge
        self._timeout = timeout_seconds

    async def expand(self, query: str) -> list[str]:
        """Generate expanded queries. Returns empty list on failure.

        The original query is NOT included in the returned list.
        """
        if not self._bridge:
            return []

        t0 = time.monotonic()
        try:
            raw = await self._bridge.chat(
                system_prompt=_EXPANSION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": query}],
                max_tokens=256,
                temperature=0.7,
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=self._timeout,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "Query expansion completed elapsed_ms=%.1f query_len=%d",
                elapsed_ms, len(query),
            )
            return self._parse(raw)
        except Exception:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.warning(
                "Query expansion failed elapsed_ms=%.1f query=%r",
                elapsed_ms, query[:100],
                exc_info=True,
            )
            return []

    @staticmethod
    def _parse(raw: str) -> list[str]:
        """Parse the LLM response into a list of query strings."""
        text = raw.strip()
        # Try to extract JSON array from the response
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            logger.warning("Query expansion response has no JSON array: %r", text[:200])
            return []
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            logger.warning("Query expansion response is not valid JSON: %r", text[:200])
            return []
        if not isinstance(parsed, list):
            return []
        result = []
        for item in parsed:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
        return result[:2]  # Cap at 2 expansions
