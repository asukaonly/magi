"""L0 working memory store with in-memory state and SQLite checkpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from .working.checkpoint import L0CheckpointMixin
from .working.execution import L0ExecutionStateMixin
from .working.goals import L0GoalStackMixin
from .working.schema import ensure_l0_checkpoint_schema
from .working.sessions import L0SessionLifecycleMixin
from .working.source_forgetting import L0SourceForgettingMixin
from .working.workbench import L0WorkbenchMixin

MAX_CONCURRENT_SESSIONS = 64
logger = get_logger(__name__)


class L0WorkingMemoryStore(
    L0SessionLifecycleMixin,
    L0GoalStackMixin,
    L0WorkbenchMixin,
    L0ExecutionStateMixin,
    L0CheckpointMixin,
    L0SourceForgettingMixin,
):
    """Maintains session-local workbench state and restores it from checkpoints."""

    def __init__(
        self,
        *,
        checkpoint_db_path: str = "~/.magi/data/memory/memory.db",
        checkpoint_interval_seconds: int = 30,
        session_timeout_seconds: int = 3600,
        restore_on_restart: bool = True,
        max_concurrent_sessions: int = MAX_CONCURRENT_SESSIONS,
    ) -> None:
        self.checkpoint_db_path = str(Path(checkpoint_db_path).expanduser())
        self.checkpoint_interval_seconds = int(checkpoint_interval_seconds)
        self.session_timeout_seconds = int(session_timeout_seconds)
        self.restore_on_restart = bool(restore_on_restart)
        self.max_concurrent_sessions = int(max_concurrent_sessions)

        self._sessions: dict[str, dict[str, Any]] = {}
        self._goal_stack: dict[str, list[dict[str, Any]]] = {}
        self._active_entities: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self._temporary_tactics: dict[str, dict[str, dict[str, Any]]] = {}
        self._execution_runs: dict[str, dict[str, Any]] = {}
        self._execution_pending_turns: dict[str, list[dict[str, Any]]] = {}
        self._execution_results: dict[str, list[dict[str, Any]]] = {}
        self._checkpoint_lock = asyncio.Lock()
        self._checkpoint_tasks: dict[str, asyncio.Task[None]] = {}
        self._checkpoint_versions: dict[str, int] = {}
        self._initialization_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Create checkpoint schema and optionally restore previously checkpointed state."""
        async with self._initialization_lock:
            if self._initialized:
                return

            Path(self.checkpoint_db_path).parent.mkdir(parents=True, exist_ok=True)
            async with sqlite_connection_async(self.checkpoint_db_path) as db:
                await ensure_l0_checkpoint_schema(db)
                await db.commit()

            if self.restore_on_restart:
                await self._restore_from_checkpoint()

            self._initialized = True

    def _schedule_checkpoint(self, session_id: str) -> None:
        """Persist dirty session state after the configured debounce interval."""

        if not self._initialized:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._checkpoint_versions[session_id] = (
            self._checkpoint_versions.get(session_id, 0) + 1
        )
        existing = self._checkpoint_tasks.get(session_id)
        if existing is not None and not existing.done():
            return

        async def _checkpoint_after_delay() -> None:
            try:
                while True:
                    scheduled_version = self._checkpoint_versions.get(session_id, 0)
                    await asyncio.sleep(self.checkpoint_interval_seconds)
                    try:
                        await self.checkpoint_session(session_id)
                    except Exception:
                        logger.exception(
                            "L0 scheduled checkpoint failed; retrying",
                            session_id=session_id,
                        )
                        continue
                    if self._checkpoint_versions.get(session_id, 0) == scheduled_version:
                        break
            except asyncio.CancelledError:
                raise
            finally:
                current = asyncio.current_task()
                if self._checkpoint_tasks.get(session_id) is current:
                    self._checkpoint_tasks.pop(session_id, None)
                    self._checkpoint_versions.pop(session_id, None)

        self._checkpoint_tasks[session_id] = loop.create_task(
            _checkpoint_after_delay(),
            name=f"l0-checkpoint:{session_id}",
        )

    def _cancel_scheduled_checkpoint(self, session_id: str) -> None:
        task = self._checkpoint_tasks.pop(session_id, None)
        self._checkpoint_versions.pop(session_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def shutdown(self) -> None:
        """Flush live workbench state and stop delayed checkpoints."""

        tasks = list(self._checkpoint_tasks.values())
        self._checkpoint_tasks.clear()
        self._checkpoint_versions.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._initialized:
            await self.checkpoint_all()
        self._initialized = False


__all__ = ["L0WorkingMemoryStore"]
