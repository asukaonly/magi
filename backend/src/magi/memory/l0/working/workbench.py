"""Prompt-facing workbench helpers for L0 working memory."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, Optional, Protocol, cast

from ..contracts import L0PromptWorkbenchProjection
from ....core.sqlite import sqlite_connection_async
from .source_forgetting import (
    active_entity_source_references,
    filter_active_entities_by_governance,
    forgotten_tactic_source_references,
    tactic_source_references,
)
from ...source_event_governance import normalize_source_event_ids


class _L0WorkbenchHostProtocol(Protocol):
    _sessions: dict[str, dict[str, Any]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]
    _checkpoint_lock: asyncio.Lock
    checkpoint_db_path: str

    async def start_session(self, *, session_id: str, **kwargs: Any) -> dict[str, Any]: ...

    async def initialize(self) -> None: ...

    def _schedule_checkpoint(self, session_id: str) -> None: ...


class L0WorkbenchMixin:
    """Own active entities, temporary tactics, and prompt workbench projection."""

    async def upsert_active_entity(
        self,
        *,
        session_id: str,
        entity_id: str,
        entity_type: str,
        snapshot: Dict[str, Any],
        relevance_score: float = 0.0,
        source_event_ids: list[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Record an active entity card for prompt-time recall."""
        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        await host.start_session(session_id=session_id)
        now = time.time()
        key = (entity_id, entity_type)
        normalized_sources = normalize_source_event_ids(source_event_ids or ())
        async with host._checkpoint_lock:
            entities = host._active_entities.setdefault(session_id, {})
            previous = entities.get(key)
            access_count = int(previous["access_count"] + 1) if previous else 1
            entity = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "relevance_score": float(relevance_score),
                "snapshot": dict(snapshot),
                "source_event_ids": list(normalized_sources),
                "loaded_at": float(previous["loaded_at"]) if previous else now,
                "last_accessed_at": now,
                "access_count": access_count,
            }
            if normalized_sources:
                async with sqlite_connection_async(host.checkpoint_db_path) as db:
                    if not await filter_active_entities_by_governance(db, [entity]):
                        return None
            entities[key] = entity
            host._schedule_checkpoint(session_id)
            return entity

    async def add_temporary_tactic(
        self,
        *,
        session_id: str,
        scope_type: str,
        scope_id: str,
        tactic_type: str,
        tactic_payload: Dict[str, Any],
        source_event_ids: list[str],
        expires_at: Optional[float] = None,
        tactic_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Add a short-lived tactic that only applies within the active session."""
        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        await host.start_session(session_id=session_id)
        tactic = {
            "tactic_id": tactic_id or f"tactic_{uuid.uuid4().hex}",
            "scope_type": scope_type,
            "scope_id": scope_id,
            "tactic_type": tactic_type,
            "tactic_payload": dict(tactic_payload),
            "source_event_ids": list(source_event_ids),
            "expires_at": expires_at,
            "created_at": time.time(),
        }
        async with host._checkpoint_lock:
            references = tactic_source_references(tactic)
            if references:
                async with sqlite_connection_async(host.checkpoint_db_path) as db:
                    if await forgotten_tactic_source_references(db, references):
                        return None
            host._temporary_tactics.setdefault(session_id, {})[tactic["tactic_id"]] = tactic
            host._schedule_checkpoint(session_id)
        return tactic

    async def get_workbench(self, session_id: str) -> dict[str, Any]:
        """Return the prompt-consumable workbench for a session."""
        host = cast(_L0WorkbenchHostProtocol, self)
        await self._expire_stale_tactics(session_id)
        async with host._checkpoint_lock:
            session = host._sessions.get(session_id)
            active_entities = list(host._active_entities.get(session_id, {}).values())
            temporary_tactics = list(host._temporary_tactics.get(session_id, {}).values())
            try:
                async with sqlite_connection_async(host.checkpoint_db_path) as db:
                    active_entities = await filter_active_entities_by_governance(
                        db,
                        active_entities,
                    )
                    forgotten_tactic_references = await forgotten_tactic_source_references(
                        db,
                        {
                            reference
                            for tactic in temporary_tactics
                            for reference in tactic_source_references(tactic)
                        },
                    )
                    temporary_tactics = [
                        tactic
                        for tactic in temporary_tactics
                        if not (tactic_source_references(tactic) & forgotten_tactic_references)
                    ]
            except Exception:
                # If governance cannot be checked, source-derived cards must not
                # reach the prompt. Source-free runtime state remains usable.
                active_entities = [
                    entity
                    for entity in active_entities
                    if active_entity_source_references(entity) == ()
                ]
                temporary_tactics = [
                    tactic for tactic in temporary_tactics if not tactic_source_references(tactic)
                ]
            return {
                "session": dict(session) if session else None,
                "goal_stack": [
                    dict(item)
                    for item in sorted(
                        (
                            goal
                            for goal in host._goal_stack.get(session_id, [])
                            if str(goal.get("status") or "")
                            in {"pending", "in_progress"}
                        ),
                        key=lambda item: (
                            -int(item.get("priority") or 0),
                            -float(item.get("created_at") or 0.0),
                        ),
                    )
                ],
                "active_entities": [
                    dict(item)
                    for item in sorted(
                        active_entities,
                        key=lambda item: (
                            -float(item["relevance_score"]),
                            -float(item["last_accessed_at"]),
                        ),
                    )
                ],
                "temporary_tactics": [
                    dict(item)
                    for item in sorted(
                        temporary_tactics,
                        key=lambda item: float(item["created_at"]),
                    )
                ],
            }

    async def forget_entity(self, entity_id: str) -> int:
        """Remove one active entity card from every live and saved session."""
        normalized_entity_id = str(entity_id or "").strip()
        if not normalized_entity_id:
            raise ValueError("entity_id must not be empty")
        host = cast(_L0WorkbenchHostProtocol, self)
        await host.initialize()
        removed_live = 0
        async with host._checkpoint_lock:
            for entities in host._active_entities.values():
                for key in [key for key in entities if key[0] == normalized_entity_id]:
                    del entities[key]
                    removed_live += 1
            async with sqlite_connection_async(host.checkpoint_db_path) as db:
                cursor = await db.execute(
                    "DELETE FROM l0_active_entities WHERE entity_id = ?",
                    (normalized_entity_id,),
                )
                removed_saved = max(int(cursor.rowcount or 0), 0)
                await db.commit()
        return max(removed_live, removed_saved)

    async def get_prompt_workbench_projection(self, session_id: str) -> L0PromptWorkbenchProjection:
        """Return the prompt-facing L0 workbench projection."""
        workbench = await self.get_workbench(session_id)
        return L0PromptWorkbenchProjection(
            session=workbench.get("session"),
            goal_stack=list(workbench.get("goal_stack", [])),
            active_entities=list(workbench.get("active_entities", [])),
            temporary_tactics=list(workbench.get("temporary_tactics", [])),
        )

    async def _expire_stale_tactics(self, session_id: str) -> None:
        host = cast(_L0WorkbenchHostProtocol, self)
        now = time.time()
        async with host._checkpoint_lock:
            tactics = host._temporary_tactics.get(session_id, {})
            removed = False
            for tactic_id, tactic in list(tactics.items()):
                expires_at = tactic.get("expires_at")
                if expires_at is not None and float(expires_at) <= now:
                    del tactics[tactic_id]
                    removed = True
            if removed:
                host._schedule_checkpoint(session_id)


__all__ = ["L0WorkbenchMixin"]
