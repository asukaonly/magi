"""Portrait orchestrator: messages → topic → snippets → persona-rendered observations.

Heavy work (topic extraction LLM + persona-lens render LLM) runs in a
background task. The HTTP-facing :meth:`get_portrait` returns within
milliseconds — either a cached payload or a cold-start indicating
``reason="computing"``. The frontend polls until the cache warms.

Single-flight: at most one background task per
``(session_id, conversation_hash, persona_id)`` key. Concurrent requests
during compute return cold-start; they do not spawn duplicate tasks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from typing import Any, Awaitable, Callable

from ...utils.diagnostic_logging import full_content_logging_enabled
from .cache import CacheKey, PortraitCache
from .contracts import (
    ChatPortraitObservation,
    ChatPortraitPayload,
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
        self._pending_jobs: dict[CacheKey, asyncio.Task] = {}
        self._pending_lock = asyncio.Lock()

    async def get_portrait(
        self,
        *,
        user_id: str,
        session_id: str,
        force: bool = False,
    ) -> ChatPortraitPayload:
        """Return a cached payload if fresh; otherwise spawn a background
        compute task and return ``reason="computing"`` cold-start.

        Subsequent polls (within compute) hit the same task and return
        cold-start again. When the task finishes successfully, cache is
        warm and the next poll returns the real payload.
        """
        persona_id = await self._active_persona_id()
        if not persona_id:
            return self._cold_start_no_persona(session_id)

        messages = await self._recent_messages(user_id, session_id)
        if not messages:
            return await self._cold_start_no_messages(session_id, persona_id)

        # Cache key uses a hash of recent user-message text, not the
        # LLM-extracted topic — otherwise we'd burn a topic-extraction LLM
        # call on every cache lookup, defeating the cache's purpose.
        key = self._cache_key(session_id, persona_id, messages)

        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        await self._ensure_compute_task(
            user_id=user_id,
            session_id=session_id,
            persona_id=persona_id,
            messages=messages,
            key=key,
        )
        return await self._stale_or_cold_start(session_id, persona_id, key)

    async def _active_persona_id(self) -> str:
        return (await self._active_persona_resolver()) or ""

    def _cold_start_no_persona(self, session_id: str) -> ChatPortraitPayload:
        logger.info("portrait cold-start: no_persona session=%s", session_id)
        return self._build_cold_start(
            session_id,
            persona_id="",
            cold_line="",
            reason="no_persona",
        )

    async def _cold_start_no_messages(
        self,
        session_id: str,
        persona_id: str,
    ) -> ChatPortraitPayload:
        logger.info("portrait cold-start: no_messages session=%s", session_id)
        return await self._cold_start_for_persona(
            session_id,
            persona_id,
            reason="no_messages",
        )

    async def _recent_messages(self, user_id: str, session_id: str) -> list[dict[str, str]]:
        messages = await self._message_loader(user_id, session_id)
        if len(messages) > self._message_window:
            return messages[-self._message_window :]
        return messages

    def _cache_key(
        self,
        session_id: str,
        persona_id: str,
        messages: list[dict[str, str]],
    ) -> CacheKey:
        return (session_id, self._hash_conversation(messages), persona_id)

    async def _ensure_compute_task(
        self,
        *,
        user_id: str,
        session_id: str,
        persona_id: str,
        messages: list[dict[str, str]],
        key: CacheKey,
    ) -> None:
        async with self._pending_lock:
            running = self._pending_jobs.get(key)
            if running is None or running.done():
                self._pending_jobs[key] = asyncio.create_task(
                    self._compute_in_background(
                        user_id=user_id,
                        session_id=session_id,
                        persona_id=persona_id,
                        messages=messages,
                        key=key,
                    )
                )
                logger.info(
                    "portrait task spawned: session=%s persona=%s",
                    session_id,
                    persona_id,
                )
            else:
                logger.debug(
                    "portrait task already running: session=%s persona=%s",
                    session_id,
                    persona_id,
                )

    async def _stale_or_cold_start(
        self,
        session_id: str,
        persona_id: str,
        key: CacheKey,
    ) -> ChatPortraitPayload:
        # Stale-while-revalidate: if we have a previous successful payload
        # for this key, return it (flagged is_stale) so the UI keeps the
        # last-known portrait visible while the background task computes
        # the next one. Without this the rail would briefly flash back to
        # the cold-start placeholder every TTL cycle.
        stale = self._cache.get_stale(key)
        if stale is not None:
            return _stale_portrait_payload(stale)

        return await self._cold_start_for_persona(
            session_id,
            persona_id,
            reason="computing",
        )

    async def _compute_in_background(
        self,
        *,
        user_id: str,
        session_id: str,
        persona_id: str,
        messages: list[dict[str, str]],
        key: CacheKey,
    ) -> None:
        """Run the full pipeline. On success, write the cache. On failure,
        do nothing — the next poll (after TTL or new conversation) retries.
        """
        try:
            topic_result = await self._extract_portrait_topic(session_id, messages)
            if topic_result is None:
                return

            snippets = await self._fetch_portrait_snippets(
                user_id=user_id,
                session_id=session_id,
                topic_result=topic_result,
            )
            if snippets is None:
                return

            observations = await self._render_portrait_observations(
                session_id=session_id,
                messages=messages,
                topic_result=topic_result,
                snippets=snippets,
                persona_config=await self._persona_config(persona_id),
            )
            if observations is None:
                return

            self._cache_portrait_payload(
                session_id,
                persona_id=persona_id,
                key=key,
                topic_result=topic_result,
                observations=observations,
            )
        except Exception as exc:
            logger.exception("portrait compute failed: session=%s err=%s", session_id, exc)
        finally:
            await self._clear_pending_compute(key)

    async def _extract_portrait_topic(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> TopicResult | None:
        topic_result = await self._topic_extractor.extract(messages)
        if topic_result.is_empty():
            logger.info(
                "portrait compute: topic_empty session=%s messages=%d",
                session_id,
                len(messages),
            )
            return None
        return topic_result

    async def _fetch_portrait_snippets(
        self,
        *,
        user_id: str,
        session_id: str,
        topic_result: TopicResult,
    ) -> list[RawMemorySnippet] | None:
        snippets = await self._snippet_fetcher(user_id, topic_result)
        if not snippets:
            if full_content_logging_enabled():
                logger.info(
                    "portrait compute: no_snippets session=%s topic=%r",
                    session_id,
                    topic_result.topic,
                )
            else:
                logger.info(
                    "portrait compute: no_snippets session=%s topic_chars=%d",
                    session_id,
                    len(topic_result.topic),
                )
            return None
        return snippets

    async def _persona_config(self, persona_id: str) -> dict[str, Any]:
        persona_detail = await self._persona_loader(persona_id)
        return (persona_detail or {}).get("config") or {}

    async def _render_portrait_observations(
        self,
        *,
        session_id: str,
        messages: list[dict[str, str]],
        topic_result: TopicResult,
        snippets: list[RawMemorySnippet],
        persona_config: dict[str, Any],
    ) -> list[ChatPortraitObservation] | None:
        observations = await self._renderer.render(
            persona_config=persona_config,
            snippets=snippets,
            recent_message_excerpt=self._last_user_message(messages),
            topic=topic_result.topic,
        )
        if not observations:
            if full_content_logging_enabled():
                logger.info(
                    "portrait compute: no_observations "
                    "session=%s topic=%r snippets=%d",
                    session_id,
                    topic_result.topic,
                    len(snippets),
                )
            else:
                logger.info(
                    "portrait compute: no_observations "
                    "session=%s topic_chars=%d snippets=%d",
                    session_id,
                    len(topic_result.topic),
                    len(snippets),
                )
            return None
        return observations

    def _cache_portrait_payload(
        self,
        session_id: str,
        *,
        persona_id: str,
        key: CacheKey,
        topic_result: TopicResult,
        observations: list[ChatPortraitObservation],
    ) -> None:
        payload = ChatPortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic=topic_result.topic,
            generated_at=int(time.time()),
            observations=observations,
            is_cold_start=False,
        )
        self._cache.set(key, payload)
        if full_content_logging_enabled():
            logger.info(
                "portrait compute: success session=%s topic=%r observations=%d",
                session_id,
                topic_result.topic,
                len(observations),
            )
        else:
            logger.info(
                "portrait compute: success "
                "session=%s topic_chars=%d observations=%d",
                session_id,
                len(topic_result.topic),
                len(observations),
            )

    async def _clear_pending_compute(self, key: CacheKey) -> None:
        async with self._pending_lock:
            # Only pop if the task is ours (paranoid; the same key map
            # should hold the same task).
            current = self._pending_jobs.get(key)
            if current is not None and current.done():
                self._pending_jobs.pop(key, None)

    def invalidate_persona(self, persona_id: str) -> None:
        self._cache.invalidate_persona(persona_id)

    async def wait_for_pending(self) -> None:
        """Await all in-flight background tasks (test helper)."""
        async with self._pending_lock:
            tasks = list(self._pending_jobs.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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

    async def _cold_start_for_persona(
        self,
        session_id: str,
        persona_id: str,
        *,
        reason: str,
    ) -> ChatPortraitPayload:
        detail = (await self._persona_loader(persona_id)) or {}
        config = detail.get("config") or {}
        interim_lines = (config.get("interim_lines") or {}).get("portrait_cold_start") or []
        line = ""
        if interim_lines:
            line = self._rand.choice(list(interim_lines))
        else:
            name = config.get("name") or "AI"
            line = f"{name} 还在认识你 · 跟我多聊聊"
        return self._build_cold_start(
            session_id,
            persona_id=persona_id,
            cold_line=line,
            reason=reason,
        )

    def _build_cold_start(
        self,
        session_id: str,
        *,
        persona_id: str,
        cold_line: str,
        reason: str,
    ) -> ChatPortraitPayload:
        return ChatPortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic="",
            generated_at=int(time.time()),
            observations=[],
            is_cold_start=True,
            cold_start_line=cold_line or None,
            cold_start_reason=reason,
        )


def _stale_portrait_payload(stale: ChatPortraitPayload) -> ChatPortraitPayload:
    return ChatPortraitPayload(
        session_id=stale.session_id,
        persona_id=stale.persona_id,
        topic=stale.topic,
        generated_at=stale.generated_at,
        observations=list(stale.observations),
        is_cold_start=False,
        cold_start_line=None,
        cold_start_reason=None,
        is_stale=True,
    )
