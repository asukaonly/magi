"""Topic and entity extraction for the persona portrait rail.

Given the last N chat messages, produce a {topic, entities} tuple. The output
feeds the cross-layer retrieval that gathers L2/L3/L4 snippets relevant to
the current conversation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .contracts import TopicResult


logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You extract the single most salient conversation topic and the named "
    "entities it revolves around. Output strict JSON: "
    '{"topic": "<short noun phrase>", "entities": ["<entity>", ...]}. '
    "If the messages have no coherent topic yet, return "
    '{"topic": "", "entities": []}.'
)


class TopicExtractor:
    """Extract conversation topic via an LLM call."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[], Any | None],
        timeout_seconds: float = 4.0,
    ) -> None:
        self._bridge_factory = bridge_factory
        self._timeout = float(timeout_seconds)

    async def extract(self, messages: list[dict[str, str]]) -> TopicResult:
        if not messages:
            return TopicResult(topic="", entities=[])
        bridge = self._bridge_factory()
        if bridge is None:
            return TopicResult(topic="", entities=[])
        prompt = self._format_messages(messages)
        try:
            payload = await asyncio.wait_for(
                bridge.complete_json(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=prompt,
                ),
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.debug("portrait topic extraction failed: %s", exc)
            return TopicResult(topic="", entities=[])
        return self._parse(payload)

    def _format_messages(self, messages: list[dict[str, str]]) -> str:
        lines = []
        for msg in messages[-10:]:
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _parse(self, payload: Any) -> TopicResult:
        if not isinstance(payload, dict):
            return TopicResult(topic="", entities=[])
        topic = str(payload.get("topic") or "").strip()
        entities_raw = payload.get("entities") or []
        if not isinstance(entities_raw, list):
            return TopicResult(topic=topic, entities=[])
        entities = [str(e).strip() for e in entities_raw if str(e).strip()]
        return TopicResult(topic=topic, entities=entities)
