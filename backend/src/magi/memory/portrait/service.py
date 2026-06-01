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

from .cache import CacheKey, PortraitCache
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
        self._pending_jobs: dict[CacheKey, asyncio.Task] = {}
        self._pending_lock = asyncio.Lock()

    async def get_portrait(
        self,
        *,
        user_id: str,
        session_id: str,
        force: bool = False,
    ) -> PortraitPayload:
        """Return a cached payload if fresh; otherwise spawn a background
        compute task and return ``reason="computing"`` cold-start.

        Subsequent polls (within compute) hit the same task and return
        cold-start again. When the task finishes successfully, cache is
        warm and the next poll returns the real payload.
        """
        persona_id = (await self._active_persona_resolver()) or ""
        if not persona_id:
            logger.info("portrait cold-start: no_persona session=%s", session_id)
            return self._build_cold_start(
                session_id, persona_id="", cold_line="", reason="no_persona",
            )

        messages = await self._message_loader(user_id, session_id)
        if len(messages) > self._message_window:
            messages = messages[-self._message_window:]
        if not messages:
            logger.info("portrait cold-start: no_messages session=%s", session_id)
            return await self._cold_start_for_persona(
                session_id, persona_id, reason="no_messages",
            )

        # Cache key uses a hash of recent user-message text, not the
        # LLM-extracted topic — otherwise we'd burn a topic-extraction LLM
        # call on every cache lookup, defeating the cache's purpose.
        conversation_hash = self._hash_conversation(messages)
        key: CacheKey = (session_id, conversation_hash, persona_id)

        if not force:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        # Single-flight: ensure at most one background task per key.
        async with self._pending_lock:
            running = self._pending_jobs.get(key)
            if running is None or running.done():
                task = asyncio.create_task(
                    self._compute_in_background(
                        user_id=user_id,
                        session_id=session_id,
                        persona_id=persona_id,
                        messages=messages,
                        key=key,
                    )
                )
                self._pending_jobs[key] = task
                logger.info(
                    "portrait task spawned: session=%s persona=%s",
                    session_id, persona_id,
                )
            else:
                logger.debug(
                    "portrait task already running: session=%s persona=%s",
                    session_id, persona_id,
                )

        # Stale-while-revalidate: if we have a previous successful payload
        # for this key, return it (flagged is_stale) so the UI keeps the
        # last-known portrait visible while the background task computes
        # the next one. Without this the rail would briefly flash back to
        # the cold-start placeholder every TTL cycle.
        stale = self._cache.get_stale(key)
        if stale is not None:
            return PortraitPayload(
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

        return await self._cold_start_for_persona(
            session_id, persona_id, reason="computing",
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
            topic_result = await self._topic_extractor.extract(messages)
            if topic_result.is_empty():
                logger.info(
                    "portrait compute: topic_empty session=%s messages=%d",
                    session_id, len(messages),
                )
                return

            snippets = await self._snippet_fetcher(user_id, topic_result)
            if not snippets:
                logger.info(
                    "portrait compute: no_snippets session=%s topic=%r",
                    session_id, topic_result.topic,
                )
                return

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
                logger.info(
                    "portrait compute: no_observations session=%s topic=%r snippets=%d",
                    session_id, topic_result.topic, len(snippets),
                )
                return

            payload = PortraitPayload(
                session_id=session_id,
                persona_id=persona_id,
                topic=topic_result.topic,
                generated_at=int(time.time()),
                observations=observations,
                is_cold_start=False,
            )
            self._cache.set(key, payload)
            logger.info(
                "portrait compute: success session=%s topic=%r observations=%d",
                session_id, topic_result.topic, len(observations),
            )
        except Exception as exc:
            logger.exception("portrait compute failed: session=%s err=%s", session_id, exc)
        finally:
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
    ) -> PortraitPayload:
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
            session_id, persona_id=persona_id, cold_line=line, reason=reason,
        )

    def _build_cold_start(
        self,
        session_id: str,
        *,
        persona_id: str,
        cold_line: str,
        reason: str,
    ) -> PortraitPayload:
        return PortraitPayload(
            session_id=session_id,
            persona_id=persona_id,
            topic="",
            generated_at=int(time.time()),
            observations=[],
            is_cold_start=True,
            cold_start_line=cold_line or None,
            cold_start_reason=reason,
        )
