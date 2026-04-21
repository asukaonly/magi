"""Memory isolation helpers for background-task runs.

A background task reuses the chat runtime's :class:`FactRecord` plumbing
to surface events, but its facts must stay *distinguishable* from
foreground chat activity so:

* downstream memory consumers can opt out of background facts during
  retrieval (e.g. a reply-composition prompt does not want to leak a
  still-running deep-research session into its context);
* observability tooling can correlate facts back to the originating
  ``BackgroundTask`` and the ``origin_session_id`` that spawned it;
* future replay/audit flows can reconstruct a background run in
  isolation.

The isolation contract is intentionally small: we stamp a reserved key
(:data:`BACKGROUND_SCOPE_KEY`) onto :class:`FactRecord.payload` with the
originating task id + session id, and provide read/write/filter helpers
plus a :class:`BackgroundFactEmitter` wrapper that the background
executor will drop in front of :meth:`TaskAgentManager.add_fact_to_agent`
in phase 3c. No changes to :class:`FactRecord` itself — that would
couple runtime contracts to a subsystem that may be disabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from ..runtime.contracts import FactRecord

__all__ = [
    "BACKGROUND_SCOPE_KEY",
    "BackgroundFactEmitter",
    "BackgroundMemoryScope",
    "get_background_scope",
    "is_background_fact",
    "tag_fact",
]


#: Reserved key stamped into ``FactRecord.payload``. Chosen with a
#: double-underscore prefix so it is visually distinct from user-facing
#: payload fields and unlikely to collide with any handler-defined key.
BACKGROUND_SCOPE_KEY = "__background__"


@dataclass(slots=True, frozen=True)
class BackgroundMemoryScope:
    """Identifies the background task that produced a given fact.

    ``background_task_id`` is the id assigned by
    :class:`BackgroundTaskStore.create_task`. ``origin_session_id`` is
    the chat session that spawned the background task — kept separate
    so the original session can still be referenced for UX breadcrumbs
    without implying the fact belongs to that session's live context.
    """

    background_task_id: str
    origin_session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "background_task_id": self.background_task_id,
            "origin_session_id": self.origin_session_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BackgroundMemoryScope":
        task_id = data.get("background_task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("background scope missing background_task_id")
        origin = data.get("origin_session_id")
        return cls(
            background_task_id=task_id,
            origin_session_id=origin if isinstance(origin, str) else None,
        )


def tag_fact(fact: FactRecord, scope: BackgroundMemoryScope) -> FactRecord:
    """Return a copy of ``fact`` with ``scope`` stamped into its payload.

    The original :class:`FactRecord` is not mutated — a shallow-copied
    payload dict is used so concurrent readers of the original fact are
    unaffected. Stamping is idempotent: a later call overwrites an
    earlier scope entry, which is what we want if a fact is ever
    re-tagged (e.g. a retry under a different ``background_task_id``).
    """
    existing_payload = fact.payload if isinstance(fact.payload, dict) else {}
    new_payload: dict[str, Any] = dict(existing_payload)
    new_payload[BACKGROUND_SCOPE_KEY] = scope.to_dict()
    return FactRecord(
        agent_id=fact.agent_id,
        event_type=fact.event_type,
        payload=new_payload,
        agent_type=fact.agent_type,
        agent_instance_id=fact.agent_instance_id,
        timestamp=fact.timestamp,
        correlation_id=fact.correlation_id,
    )


def get_background_scope(fact: FactRecord) -> BackgroundMemoryScope | None:
    """Return the scope stamped on ``fact``, or ``None`` if absent."""
    payload = fact.payload if isinstance(fact.payload, dict) else None
    if not payload:
        return None
    raw = payload.get(BACKGROUND_SCOPE_KEY)
    if not isinstance(raw, Mapping):
        return None
    try:
        return BackgroundMemoryScope.from_dict(raw)
    except ValueError:
        return None


def is_background_fact(fact: FactRecord) -> bool:
    """Quick predicate for memory-retrieval filters."""
    return get_background_scope(fact) is not None


#: Signature of the downstream emit target wrapped by
#: :class:`BackgroundFactEmitter`. A ``bool`` return indicates whether
#: the receiver accepted/enqueued the fact — mirrors
#: :meth:`TaskAgentManager.add_fact_to_agent`.
FactEmitFn = Callable[[FactRecord], Awaitable[bool]]


class BackgroundFactEmitter:
    """Tag-every-fact middleware between the executor and fact routing.

    Phase 3c wires this in front of
    :meth:`TaskAgentManager.add_fact_to_agent` inside the background
    executor so every fact the background run emits is stamped before
    the routing layer ever sees it. Keeping the tagging at this boundary
    avoids scattering scope plumbing through every handler.
    """

    __slots__ = ("_delegate", "_scope")

    def __init__(self, delegate: FactEmitFn, scope: BackgroundMemoryScope) -> None:
        self._delegate = delegate
        self._scope = scope

    @property
    def scope(self) -> BackgroundMemoryScope:
        return self._scope

    async def emit(self, fact: FactRecord) -> bool:
        tagged = tag_fact(fact, self._scope)
        return await self._delegate(tagged)
