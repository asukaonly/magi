"""Control-plane service for ask-user interaction lifecycle."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .common import InteractionTimeoutError
from .common import events as control_events
from . import provider as control_provider
from ..core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ControlAskRequest:
    """Input for one user-facing ask interaction."""

    session_id: str
    user_id: str | None
    turn_id: str | None
    question: str
    options: list[str]
    allow_free_text: bool
    timeout_seconds: float | None
    background: bool = False
    background_task_id: str | None = None
    background_port: Any = None
    cancellation: Any = None


@dataclass(frozen=True)
class ControlAskOutcome:
    """Result of an ask interaction."""

    answered: bool
    answer: str | None
    resolution: str
    timed_out: bool


class ControlAskService:
    """Owns opening, waiting, closing, and publishing ask state changes."""

    def __init__(self, *, session_store: Any, interaction_broker: Any) -> None:
        self._store = session_store
        self._broker = interaction_broker

    @classmethod
    def from_runtime(cls) -> "ControlAskService":
        """Build from active control-plane runtime bindings."""
        return cls(
            session_store=control_provider.resolve_control_session_store(),
            interaction_broker=control_provider.resolve_control_interaction_broker(),
        )

    async def ask(self, request: ControlAskRequest) -> ControlAskOutcome:
        sid = request.session_id
        is_background = bool(request.background)
        bg_task_id = request.background_task_id or None
        manager = request.background_port if bg_task_id is not None else None
        timeout_value = (
            float(request.timeout_seconds)
            if request.timeout_seconds is not None
            else None
        )

        request_id = uuid.uuid4().hex
        answer_task = asyncio.create_task(
            self._broker.wait(
                interaction_id=request_id,
                kind="ask",
                timeout_seconds=timeout_value,
            ),
            name=f"ask-user-question-{request_id}",
        )
        cancel_task: asyncio.Task[None] | None = None
        if request.cancellation is not None:
            cancel_task = asyncio.create_task(
                request.cancellation.wait(),
                name=f"ask-user-question-cancel-{request_id}",
            )

        await asyncio.sleep(0)
        if request.cancellation is not None and await request.cancellation.is_cancelled():
            await self._cancel_wait_tasks(answer_task, cancel_task)
            return ControlAskOutcome(
                answered=False,
                answer=None,
                resolution="cancelled",
                timed_out=False,
            )

        try:
            ask = await self._store.open_ask(
                sid,
                question=request.question,
                options=request.options,
                allow_free_text=request.allow_free_text,
                timeout_seconds=timeout_value,
                request_id=request_id,
            )
        except Exception:
            await self._cancel_wait_tasks(answer_task, cancel_task)
            raise

        await self._publish_opened(
            request=request,
            ask=ask,
            is_background=is_background,
            bg_task_id=bg_task_id,
            manager=manager,
            timeout_value=timeout_value,
        )

        pending_tasks: set[asyncio.Task[Any]] = {answer_task}
        if cancel_task is not None:
            pending_tasks.add(cancel_task)

        try:
            done, pending = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if (
                cancel_task is not None
                and cancel_task in done
                and await request.cancellation.is_cancelled()
            ):
                answer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await answer_task
                await self._close_cancelled(
                    request=request,
                    ask=ask,
                    is_background=is_background,
                    bg_task_id=bg_task_id,
                    manager=manager,
                )
                return ControlAskOutcome(
                    answered=False,
                    answer=None,
                    resolution="cancelled",
                    timed_out=False,
                )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            answer = await answer_task
        except InteractionTimeoutError:
            await self._close_timeout(
                request=request,
                is_background=is_background,
                bg_task_id=bg_task_id,
                manager=manager,
            )
            return ControlAskOutcome(
                answered=False,
                answer=None,
                resolution="timeout",
                timed_out=True,
            )

        answer_text = str(answer) if answer is not None else ""
        closed_ask = await self._store.close_ask(
            sid, answer=answer_text, resolution="user"
        )
        if closed_ask is not None:
            try:
                await control_events.publish_control_ask_answered(
                    session_id=sid,
                    user_id=request.user_id,
                    turn_id=request.turn_id,
                    ask=closed_ask,
                    answer=answer_text,
                    background=is_background,
                )
            except Exception:
                logger.debug("ask_user_question.persist_response_failed", exc_info=True)
        await self._resume_background(bg_task_id=bg_task_id, manager=manager)
        logger.info(
            "ask_user_question.answered",
            session_id=sid,
            request_id=ask.request_id,
            length=len(answer_text),
        )
        if is_background:
            try:
                await control_events.publish_control_event(
                    "control.background.resumed",
                    {
                        "session_id": sid,
                        "request_id": ask.request_id,
                    },
                    session_id=sid,
                    turn_id=request.turn_id,
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug("ask_user_question.resume_event_failed", exc_info=True)
        return ControlAskOutcome(
            answered=True,
            answer=answer_text,
            resolution="user",
            timed_out=False,
        )

    async def _publish_opened(
        self,
        *,
        request: ControlAskRequest,
        ask: Any,
        is_background: bool,
        bg_task_id: str | None,
        manager: Any,
        timeout_value: float | None,
    ) -> None:
        try:
            await control_events.publish_control_ask_requested(
                session_id=request.session_id,
                user_id=request.user_id,
                turn_id=request.turn_id,
                ask=ask,
                background=is_background,
            )
        except Exception:
            logger.debug("ask_user_question.persist_request_failed", exc_info=True)

        logger.info(
            "ask_user_question.opened",
            session_id=request.session_id,
            request_id=ask.request_id,
            background=is_background,
            bg_task_id=bg_task_id,
        )
        if bg_task_id is not None and manager is not None:
            try:
                await manager.suspend_waiting_user(
                    bg_task_id, reason="awaiting_user_answer"
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "ask_user_question.manager_suspend_failed",
                    exc_info=True,
                )
        try:
            await control_events.publish_control_event(
                "control.ask.requested",
                {
                    "request_id": ask.request_id,
                    "session_id": request.session_id,
                    "question": request.question,
                    "options": list(request.options or []),
                    "allow_free_text": request.allow_free_text,
                    "timeout_seconds": timeout_value,
                    "created_at_ms": int(ask.asked_at * 1000),
                    "expires_at_ms": (
                        int(ask.expires_at * 1000) if ask.expires_at else None
                    ),
                    "background": is_background,
                },
                session_id=request.session_id,
                turn_id=request.turn_id,
            )
            if is_background:
                await control_events.publish_control_event(
                    "control.background.suspended",
                    {
                        "session_id": request.session_id,
                        "request_id": ask.request_id,
                        "reason": "awaiting_user_answer",
                        "timeout_seconds": timeout_value,
                    },
                    session_id=request.session_id,
                    turn_id=request.turn_id,
                )
        except Exception:  # pragma: no cover - defensive
            logger.debug("ask_user_question.event_failed", exc_info=True)

    async def _close_cancelled(
        self,
        *,
        request: ControlAskRequest,
        ask: Any,
        is_background: bool,
        bg_task_id: str | None,
        manager: Any,
    ) -> None:
        closed_ask = await self._store.close_ask(
            request.session_id, answer=None, resolution="cancelled"
        )
        if closed_ask is not None:
            try:
                await control_events.publish_control_ask_requested(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    turn_id=request.turn_id,
                    ask=closed_ask,
                    background=is_background,
                )
            except Exception:
                logger.debug("ask_user_question.persist_cancelled_failed", exc_info=True)
        await self._resume_background(bg_task_id=bg_task_id, manager=manager)
        logger.info(
            "ask_user_question.cancelled",
            session_id=request.session_id,
            request_id=ask.request_id,
            reason=getattr(request.cancellation, "reason", None),
        )

    async def _close_timeout(
        self,
        *,
        request: ControlAskRequest,
        is_background: bool,
        bg_task_id: str | None,
        manager: Any,
    ) -> None:
        closed_ask = await self._store.close_ask(
            request.session_id, answer=None, resolution="timeout"
        )
        if closed_ask is not None:
            try:
                await control_events.publish_control_ask_requested(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    turn_id=request.turn_id,
                    ask=closed_ask,
                    background=is_background,
                )
            except Exception:
                logger.debug("ask_user_question.persist_timeout_failed", exc_info=True)
        await self._resume_background(bg_task_id=bg_task_id, manager=manager)

    @staticmethod
    async def _resume_background(*, bg_task_id: str | None, manager: Any) -> None:
        if bg_task_id is None or manager is None:
            return
        try:
            await manager.resume_from_wait(bg_task_id)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "ask_user_question.manager_resume_failed",
                exc_info=True,
            )

    @staticmethod
    async def _cancel_wait_tasks(
        answer_task: asyncio.Task[Any],
        cancel_task: asyncio.Task[Any] | None,
    ) -> None:
        answer_task.cancel()
        if cancel_task is not None:
            cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await answer_task
        if cancel_task is not None:
            with suppress(asyncio.CancelledError):
                await cancel_task


__all__ = ["ControlAskOutcome", "ControlAskRequest", "ControlAskService"]
