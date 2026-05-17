"""Portrait orchestrator: messages → topic → snippets → persona-rendered observations."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from typing import Any, Awaitable, Callable

from .cache import PortraitCache
from .contracts import (
    PortraitPayload,
    RawMemorySnippet,
    TopicResult,
)


logger = logging.getLogger(__name__)


SnippetFetcher = Callable[[str, TopicResult], Awaitable[list[RawMemorySnippet]]]
MessageLoader = Callable[[str, str], Awaitable[list[dict[str, str]]]]
PersonaLoader = Callable[[str], Awaitable[dict[str, Any] | None]]
ActivePersonaResolver = Callable[[], Awaitable[str | None]]


class PortraitService:
    """Compose topic extraction, snippet fetching, and persona-lens rendering."""

    def __init__(
        self,
        *,
        topic_extractor: Any,
        renderer: Any,
        snippet_fetcher: SnippetFetcher,
        persona_loader: PersonaLoader,
        message_loader: MessageLoader,
        active_persona_resolver: ActivePersonaResolver,
        cache: PortraitCache | None = None,
        message_window: int = 10,
        random_seed: int | None = None,
    ) -> None:
        self._topic_extractor = topic_extractor
        self._renderer = renderer
        self._snippet_fetcher = snippet_fetcher
        self._persona_loader = persona_loader
        self._message_loader = message_loader
        self._active_persona_resolver = active_persona_resolver
        self._cache = cache or PortraitCache()
        self._message_window = int(message_window)
        self._rand = random.Random(random_seed)

    async def get_portrait(
        self,
        *,
        user_id: str,
        session_id: str,
        force: bool = False,
    ) -> PortraitPayload:
        persona_id = (await self._active_persona_resolver()) or ""
        if not persona_id:
            return self._build_cold_start(session_id, persona_id="", cold_line="")

        messages = await self._message_loader(user_id, session_id)
        if len(messages) > self._message_window:
            messages = messages[-self._message_window:]

        # Cache key uses a hash of recent user-message text, not the
        # LLM-extracted topic — otherwise we'd burn a topic-extraction LLM
        # call on every cache lookup, defeating the cache's purpose.
        # Topic shifts within the session still bust the cache because the
        # last user messages change.
        conversation_hash = self._hash_conversation(messages)

        key = (session_id, conversation_hash, persona_id)
        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        topic_result = await self._topic_extractor.extract(messages)
        snippets = await self._snippet_fetcher(user_id, topic_result)
        if not snippets:
            return await self._cold_start_for_persona(session_id, persona_id)

        persona_detail = await self._persona_loader(persona_id)
        persona_config = (persona_detail or {}).get("config") or {}

        recent_excerpt = self._last_user_message(messages)
        observations = await self._renderer.render(
            persona_config=persona_config,
            snippets=snippets,
            recent_message_excerpt=recent_excerpt,
            topic=topic_result.topic,
        )

        if not observations:
            return await self._cold_start_for_persona(session_id, persona_id)

        payload = PortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic=topic_result.topic,
            generated_at=int(time.time()),
            observations=observations,
            is_cold_start=False,
        )
        self._cache.set(key, payload)
        return payload

    def invalidate_persona(self, persona_id: str) -> None:
        self._cache.invalidate_persona(persona_id)

    def _hash_conversation(self, messages: list[dict[str, str]]) -> str:
        """Hash the last few user messages as a cheap topic proxy."""
        user_texts: list[str] = []
        for msg in reversed(messages):
            if str(msg.get("role") or "") != "user":
                continue
            content = str(msg.get("content") or "").strip()
            if content:
                user_texts.append(content)
            if len(user_texts) >= 3:
                break
        raw = "|".join(reversed(user_texts)).encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]

    def _last_user_message(self, messages: list[dict[str, str]]) -> str:
        for msg in reversed(messages):
            if str(msg.get("role") or "") == "user":
                return str(msg.get("content") or "")
        return ""

    async def _cold_start_for_persona(self, session_id: str, persona_id: str) -> PortraitPayload:
        detail = (await self._persona_loader(persona_id)) or {}
        config = detail.get("config") or {}
        interim_lines = (config.get("interim_lines") or {}).get("portrait_cold_start") or []
        line = ""
        if interim_lines:
            line = self._rand.choice(list(interim_lines))
        else:
            name = config.get("name") or "AI"
            line = f"{name} 还在认识你 · 跟我多聊聊"
        return self._build_cold_start(session_id, persona_id=persona_id, cold_line=line)

    def _build_cold_start(
        self,
        session_id: str,
        *,
        persona_id: str,
        cold_line: str,
    ) -> PortraitPayload:
        return PortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic="",
            generated_at=int(time.time()),
            observations=[],
            is_cold_start=True,
            cold_start_line=cold_line or None,
        )
