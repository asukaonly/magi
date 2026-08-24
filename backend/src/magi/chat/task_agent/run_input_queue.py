"""Safe-boundary input queue for one active agent run."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from magi.control.run_control import RunInputInbox, RunInputMessage
from magi.agent.task_agents.handlers.run_contracts import RUN_INPUT_DISPOSITION

from .session_run_decisions import TurnSupersession

if TYPE_CHECKING:
    from .run_store import SessionRunStore


class RunInputQueue(RunInputInbox):
    """Drain persisted user messages into model context exactly once."""

    def __init__(
        self,
        *,
        run_store: "SessionRunStore",
        session_id: str,
        run_id: str,
        revision: int,
        root_turn_id: str | None,
        on_consumed: Callable[[list[TurnSupersession]], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._run_store = run_store
        self._session_id = session_id
        self._run_id = run_id
        self._revision = int(revision)
        self._root_turn_id = str(root_turn_id or "").strip()
        self._on_consumed = on_consumed

    async def drain(self) -> list[RunInputMessage]:
        explicit = await super().drain()
        active_run = self._run_store.get_active_run(self._session_id)
        if (
            active_run is None
            or active_run.run_id != self._run_id
            or int(active_run.revision) != self._revision
            or active_run.status != "running"
        ):
            return explicit
        pending = self._run_store.consume_pending_turns(
            self._session_id,
            revision=self._revision,
            disposition=RUN_INPUT_DISPOSITION,
        )
        if not pending:
            return explicit
        supersessions = [
            TurnSupersession(
                turn_id=item.turn_id,
                anchor_turn_id=self._root_turn_id,
                reason=RUN_INPUT_DISPOSITION,
            )
            for item in pending
            if item.turn_id and self._root_turn_id
        ]
        if supersessions and self._on_consumed is not None:
            try:
                await self._on_consumed(supersessions)
            except Exception:
                for item in pending:
                    self._run_store.append_pending_turn(
                        self._session_id,
                        item.turn_id,
                        item.content,
                        disposition=RUN_INPUT_DISPOSITION,
                    )
                raise
        injected = [
            RunInputMessage(
                content=item.content,
                reason=RUN_INPUT_DISPOSITION,
                metadata={
                    "turn_id": item.turn_id,
                    "run_id": self._run_id,
                    "revision": self._revision,
                },
            )
            for item in pending
        ]
        return [*explicit, *injected]


__all__ = ["RUN_INPUT_DISPOSITION", "RunInputQueue"]
