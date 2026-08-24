"""Chat turn state persistence for post-processing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from magi.chat import ChatStore, ChatTurnRecord
from ..session_run_decisions import supersession_terminal_status


@dataclass(frozen=True, slots=True)
class ChatTurnWriteResult:
    """Existing turn state plus the resolved response mode for follow-up writes."""

    turn: ChatTurnRecord
    turn_id: str
    response_mode: str
    ux_plan: dict[str, Any]


class ChatTurnStateWriter:
    """Persist durable per-turn state without writing transcript messages."""

    def __init__(
        self,
        *,
        chat_store: ChatStore | None,
        trace_id_factory: Callable[[str], str],
    ) -> None:
        self._chat_store = chat_store
        self._trace_id_factory = trace_id_factory

    async def persist_turn_ux_plan(
        self,
        *,
        turn_id: str,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        updated_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> ChatTurnWriteResult | None:
        if self._chat_store is None or not ux_plan:
            return None
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return None
        existing_turn = await self._chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return None
        response_mode = str(ux_plan.get("assistant_surface_mode") or existing_turn.response_mode or "final_only")
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(normalized_turn_id),
                status="running",
                response_mode=response_mode,
                execution_mode=execution_mode or existing_turn.execution_mode,
                ux_plan_json=json.dumps(ux_plan, ensure_ascii=False),
                created_at_ms=existing_turn.created_at_ms,
                updated_at_ms=updated_at_ms,
                completed_at_ms=None,
                error_text=existing_turn.error_text,
                run_id=run_id or existing_turn.run_id,
                run_revision=run_revision if run_id is not None else existing_turn.run_revision,
                run_disposition=run_disposition or existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        return ChatTurnWriteResult(
            turn=existing_turn,
            turn_id=normalized_turn_id,
            response_mode=response_mode,
            ux_plan=ux_plan,
        )

    async def complete_turn(
        self,
        *,
        turn_id: str | None,
        execution_mode: str | None,
        ux_plan: dict[str, Any] | None,
        started_at_ms: int,
        completed_at_ms: int,
        run_id: str | None = None,
        run_revision: int = 0,
        run_disposition: str | None = None,
    ) -> ChatTurnWriteResult | None:
        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None
        existing_turn = await self._chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return None
        normalized_ux_plan = ux_plan if isinstance(ux_plan, dict) else {}
        response_mode = str(
            normalized_ux_plan.get("assistant_surface_mode") or existing_turn.response_mode or "final_only"
        )
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(normalized_turn_id),
                status="completed",
                response_mode=response_mode,
                execution_mode=execution_mode or existing_turn.execution_mode,
                ux_plan_json=(
                    json.dumps(normalized_ux_plan, ensure_ascii=False)
                    if normalized_ux_plan
                    else existing_turn.ux_plan_json
                ),
                created_at_ms=existing_turn.created_at_ms or started_at_ms,
                updated_at_ms=completed_at_ms,
                completed_at_ms=completed_at_ms,
                error_text=existing_turn.error_text,
                run_id=run_id or existing_turn.run_id,
                run_revision=run_revision if run_id is not None else existing_turn.run_revision,
                run_disposition=run_disposition or existing_turn.run_disposition,
                response_anchor_turn_id=existing_turn.response_anchor_turn_id,
                superseded_by_turn_id=existing_turn.superseded_by_turn_id,
                supersession_reason=existing_turn.supersession_reason,
            )
        )
        return ChatTurnWriteResult(
            turn=existing_turn,
            turn_id=normalized_turn_id,
            response_mode=response_mode,
            ux_plan=normalized_ux_plan,
        )

    async def resolve_turn_completion(
        self,
        *,
        turn_id: str | None,
        ux_plan: dict[str, Any] | None,
    ) -> ChatTurnWriteResult | None:
        """Load the turn and response mode before committing visible output."""

        normalized_turn_id = str(turn_id or "").strip()
        if self._chat_store is None or not normalized_turn_id:
            return None
        existing_turn = await self._chat_store.get_turn(normalized_turn_id)
        if existing_turn is None:
            return None
        normalized_ux_plan = ux_plan if isinstance(ux_plan, dict) else {}
        response_mode = str(
            normalized_ux_plan.get("assistant_surface_mode")
            or existing_turn.response_mode
            or "final_only"
        )
        return ChatTurnWriteResult(
            turn=existing_turn,
            turn_id=normalized_turn_id,
            response_mode=response_mode,
            ux_plan=normalized_ux_plan,
        )

    async def persist_turn_supersession(
        self,
        *,
        turn_id: str,
        anchor_turn_id: str,
        reason: str,
        updated_at_ms: int,
    ) -> None:
        if self._chat_store is None:
            return
        existing_turn = await self._chat_store.get_turn(turn_id)
        if existing_turn is None:
            return
        status = supersession_terminal_status(reason)
        await self._chat_store.upsert_turn(
            ChatTurnRecord(
                turn_id=existing_turn.turn_id,
                session_id=existing_turn.session_id,
                user_id=existing_turn.user_id,
                trace_id=existing_turn.trace_id or self._trace_id_factory(turn_id),
                status=status,
                response_mode=existing_turn.response_mode,
                execution_mode=existing_turn.execution_mode,
                ux_plan_json=existing_turn.ux_plan_json,
                created_at_ms=existing_turn.created_at_ms,
                updated_at_ms=updated_at_ms,
                completed_at_ms=updated_at_ms,
                error_text=existing_turn.error_text,
                run_id=existing_turn.run_id,
                run_revision=existing_turn.run_revision,
                run_disposition=existing_turn.run_disposition,
                response_anchor_turn_id=anchor_turn_id,
                superseded_by_turn_id=anchor_turn_id,
                supersession_reason=status,
            )
        )


__all__ = ["ChatTurnStateWriter", "ChatTurnWriteResult"]
