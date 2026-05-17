"""In-memory registry of hook handlers grouped by event type."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import Dict, List, Optional

from .contracts import HookEventType, HookHandler

logger = logging.getLogger(__name__)


class HookRegistry:
    """Thread-safe registry of hook handlers.

    Handler order within an event type is the registration order — important
    because ``MODIFY`` decisions apply in sequence and the first ``DENY``
    short-circuits the rest.
    """

    def __init__(self) -> None:
        self._handlers: Dict[HookEventType, List[HookHandler]] = defaultdict(list)
        self._matchers: Dict[int, Optional[str]] = {}
        self._sources: Dict[int, Optional[str]] = {}
        self._lock = threading.Lock()

    def register(
        self,
        event_type: HookEventType,
        handler: HookHandler,
        *,
        matcher: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(
                f"Hook handler for {event_type.value} must be async; got {type(handler).__name__}"
            )
        with self._lock:
            self._handlers[event_type].append(handler)
            self._matchers[id(handler)] = matcher
            self._sources[id(handler)] = source
        logger.debug(
            "registered hook handler event=%s matcher=%s source=%s",
            event_type.value,
            matcher,
            source,
        )

    def unregister(self, event_type: HookEventType, handler: HookHandler) -> bool:
        with self._lock:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                return False
            self._matchers.pop(id(handler), None)
            self._sources.pop(id(handler), None)
        return True

    def clear(self, event_type: Optional[HookEventType] = None) -> None:
        with self._lock:
            if event_type is None:
                self._handlers.clear()
                self._matchers.clear()
                self._sources.clear()
            else:
                for h in self._handlers.get(event_type, []):
                    self._matchers.pop(id(h), None)
                    self._sources.pop(id(h), None)
                self._handlers.pop(event_type, None)

    def handlers_for(self, event_type: HookEventType, matcher_key: Optional[str]) -> List[HookHandler]:
        """Return handlers whose matcher accepts ``matcher_key``.

        A handler with ``matcher=None`` matches everything. Otherwise the
        matcher is interpreted as a substring filter against ``matcher_key``
        (case-sensitive). More sophisticated regex/glob behaviour is left for
        a future iteration; this keeps Phase 2 minimal.
        """
        with self._lock:
            registered = list(self._handlers.get(event_type, ()))
            local_matchers = dict(self._matchers)

        if not registered:
            return []
        result: List[HookHandler] = []
        for handler in registered:
            matcher = local_matchers.get(id(handler))
            if matcher is None or not matcher_key:
                result.append(handler)
                continue
            if matcher in matcher_key:
                result.append(handler)
        return result

    def source_of(self, handler: HookHandler) -> Optional[str]:
        with self._lock:
            return self._sources.get(id(handler))

    def total(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._handlers.values())


__all__ = ["HookRegistry"]
