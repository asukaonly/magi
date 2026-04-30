"""Prompt-facing workbench helpers for L0 working memory."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional, Protocol, cast

from ..contracts import L0PromptWorkbenchProjection
from .projection import build_execution_summary


class _L0WorkbenchHostProtocol(Protocol):
    _sessions: dict[str, dict[str, Any]]
    _goal_stack: dict[str, list[dict[str, Any]]]
    _active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]]
    _temporary_tactics: dict[str, dict[str, dict[str, Any]]]

    async def start_session(self, *, session_id: str, **kwargs: Any) -> dict[str, Any]: ...

    def get_execution_state_sync(self, session_id: str) -> dict[str, Any]: ...


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
    ) -> dict[str, Any]:
        """Record an active entity card for prompt-time recall."""
        host = cast(_L0WorkbenchHostProtocol, self)
        await host.start_session(session_id=session_id)
        now = time.time()
        key = (entity_id, entity_type)
        previous = host._active_entities[session_id].get(key)
        access_count = int(previous["access_count"] + 1) if previous else 1
        entity = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "relevance_score": float(relevance_score),
            "snapshot": dict(snapshot),
            "loaded_at": float(previous["loaded_at"]) if previous else now,
            "last_accessed_at": now,
            "access_count": access_count,
        }
        host._active_entities[session_id][key] = entity
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
    ) -> dict[str, Any]:
        """Add a short-lived tactic that only applies within the active session."""
        host = cast(_L0WorkbenchHostProtocol, self)
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
        host._temporary_tactics[session_id][tactic["tactic_id"]] = tactic
        return tactic

    async def get_workbench(self, session_id: str) -> dict[str, Any]:
        """Return the prompt-consumable workbench for a session."""
        host = cast(_L0WorkbenchHostProtocol, self)
        await self._expire_stale_tactics(session_id)
        session = host._sessions.get(session_id)
        return {
            "session": dict(session) if session else None,
            "goal_stack": [dict(item) for item in host._goal_stack.get(session_id, [])],
            "active_entities": [
                dict(item)
                for item in sorted(
                    host._active_entities.get(session_id, {}).values(),
                    key=lambda item: (-float(item["relevance_score"]), -float(item["last_accessed_at"])),
                )
            ],
            "temporary_tactics": [
                dict(item)
                for item in sorted(
                    host._temporary_tactics.get(session_id, {}).values(),
                    key=lambda item: float(item["created_at"]),
                )
            ],
        }

    async def get_prompt_workbench_projection(self, session_id: str) -> L0PromptWorkbenchProjection:
        """Return the prompt-facing L0 projection with execution state summarized."""
        host = cast(_L0WorkbenchHostProtocol, self)
        workbench = await self.get_workbench(session_id)
        execution_state = host.get_execution_state_sync(session_id)
        run = execution_state.get("run")
        pending_turns = execution_state.get("pending_turns", [])

        projection = L0PromptWorkbenchProjection(
            session=workbench.get("session"),
            goal_stack=list(workbench.get("goal_stack", [])),
            active_entities=list(workbench.get("active_entities", [])),
            temporary_tactics=list(workbench.get("temporary_tactics", [])),
        )
        projection.execution_summary = build_execution_summary(
            run=run if isinstance(run, dict) else None,
            pending_turns=[item for item in pending_turns if isinstance(item, dict)],
            accepted_results=[
                item
                for item in execution_state.get("accepted_results", [])
                if isinstance(item, dict)
            ],
        )
        return projection

    async def _expire_stale_tactics(self, session_id: str) -> None:
        host = cast(_L0WorkbenchHostProtocol, self)
        now = time.time()
        tactics = host._temporary_tactics.get(session_id, {})
        for tactic_id, tactic in list(tactics.items()):
            expires_at = tactic.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                del tactics[tactic_id]


__all__ = ["L0WorkbenchMixin"]
