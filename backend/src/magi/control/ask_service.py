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
from .session_store import ControlSessionClearedError
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


@dataclass(frozen=True)
class _AskState:
    sid: str
    is_background: bool
    bg_task_id: str | None
    manager: Any
    timeout_value: float | None
    request_id: str
    session_generation: int
    broker_generation: int


@dataclass(frozen=True)
class _AskWaitTasks:
    answer_task: asyncio.Task[Any]
    cancel_task: asyncio.Task[Any] | None


@dataclass(frozen=True)
class _AskWaitResult:
    answer: Any = None
    cancelled: bool = False


def _cancelled_outcome() -> ControlAskOutcome:
    return ControlAskOutcome(
        answered=False,
        answer=None,
        resolution="cancelled",
        timed_out=False,
    )


def _timeout_outcome() -> ControlAskOutcome:
    return ControlAskOutcome(
        answered=False,
        answer=None,
        resolution="timeout",
        timed_out=True,
    )


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
        if (
            not request.allow_free_text
            and not any(str(item or "").strip() for item in request.options)
        ):
            raise ValueError(
                "A choice-only question requires at least one non-empty option"
            )
        state = self._ask_state(request)
        wait_tasks = self._start_wait_tasks(request, state)

        if await self._cancelled_before_open(request, wait_tasks):
            return _cancelled_outcome()

        try:
            async with self._store.user_content_operation(
                expected_generation=state.session_generation
            ):
                ask = await self._store.open_ask(
                    state.sid,
                    question=request.question,
                    options=request.options,
                    allow_free_text=request.allow_free_text,
                    timeout_seconds=state.timeout_value,
                    request_id=state.request_id,
                )
        except Exception:
            await self._cancel_wait_tasks(
                wait_tasks.answer_task,
                wait_tasks.cancel_task,
            )
            raise

        try:
            async with self._store.user_content_operation(
                expected_generation=ask.clear_generation
            ):
                if self._store.ask_state(state.sid) is not ask:
                    raise ControlSessionClearedError(
                        "ask state was replaced before it could be published"
                    )
                await self._publish_opened(
                    request=request,
                    ask=ask,
                    is_background=state.is_background,
                    bg_task_id=state.bg_task_id,
                    manager=state.manager,
                    timeout_value=state.timeout_value,
                )
        except Exception:
            await self._cancel_wait_tasks(
                wait_tasks.answer_task,
                wait_tasks.cancel_task,
            )
            raise

        try:
            wait_result = await self._wait_for_answer_or_cancel(
                request=request,
                ask=ask,
                state=state,
                wait_tasks=wait_tasks,
            )
        except InteractionTimeoutError:
            await self._close_timeout(
                request=request,
                ask=ask,
                is_background=state.is_background,
                bg_task_id=state.bg_task_id,
                manager=state.manager,
            )
            return _timeout_outcome()

        if wait_result.cancelled:
            return _cancelled_outcome()
        return await self._answered_outcome(
            request=request,
            ask=ask,
            state=state,
            answer=wait_result.answer,
        )

    def _ask_state(self, request: ControlAskRequest) -> _AskState:
        bg_task_id = request.background_task_id or None
        return _AskState(
            sid=request.session_id,
            is_background=bool(request.background),
            bg_task_id=bg_task_id,
            manager=request.background_port if bg_task_id is not None else None,
            timeout_value=(
                float(request.timeout_seconds) if request.timeout_seconds is not None else None
            ),
            request_id=uuid.uuid4().hex,
            session_generation=self._store.user_content_generation(),
            broker_generation=self._broker.user_content_generation(),
        )

    def _start_wait_tasks(
        self,
        request: ControlAskRequest,
        state: _AskState,
    ) -> _AskWaitTasks:
        answer_task = asyncio.create_task(
            self._broker.wait(
                interaction_id=state.request_id,
                kind="ask",
                timeout_seconds=state.timeout_value,
                metadata={
                    "allow_free_text": request.allow_free_text,
                    "options": [
                        option
                        for option in (
                            str(item or "").strip()
                            for item in request.options
                        )
                        if option
                    ],
                },
                expected_generation=state.broker_generation,
            ),
            name=f"ask-user-question-{state.request_id}",
        )
        cancel_task: asyncio.Task[Any] | None = None
        if request.cancellation is not None:
            cancel_task = asyncio.create_task(
                request.cancellation.wait(),
                name=f"ask-user-question-cancel-{state.request_id}",
            )
        return _AskWaitTasks(answer_task=answer_task, cancel_task=cancel_task)

    async def _cancelled_before_open(
        self,
        request: ControlAskRequest,
        wait_tasks: _AskWaitTasks,
    ) -> bool:
        await asyncio.sleep(0)
        if request.cancellation is None:
            return False
        if not await request.cancellation.is_cancelled():
            return False
        await self._cancel_wait_tasks(wait_tasks.answer_task, wait_tasks.cancel_task)
        return True

    async def _wait_for_answer_or_cancel(
        self,
        *,
        request: ControlAskRequest,
        ask: Any,
        state: _AskState,
        wait_tasks: _AskWaitTasks,
    ) -> _AskWaitResult:
        pending_tasks: set[asyncio.Task[Any]] = {wait_tasks.answer_task}
        if wait_tasks.cancel_task is not None:
            pending_tasks.add(wait_tasks.cancel_task)

        done, pending = await asyncio.wait(
            pending_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if await self._did_cancel(request, wait_tasks, done):
            wait_tasks.answer_task.cancel()
            with suppress(asyncio.CancelledError):
                await wait_tasks.answer_task
            await self._close_cancelled(
                request=request,
                ask=ask,
                is_background=state.is_background,
                bg_task_id=state.bg_task_id,
                manager=state.manager,
            )
            return _AskWaitResult(cancelled=True)

        await self._cancel_pending_tasks(pending)
        return _AskWaitResult(answer=await wait_tasks.answer_task)

    @staticmethod
    async def _did_cancel(
        request: ControlAskRequest,
        wait_tasks: _AskWaitTasks,
        done: set[asyncio.Task[Any]],
    ) -> bool:
        return (
            request.cancellation is not None
            and wait_tasks.cancel_task is not None
            and wait_tasks.cancel_task in done
            and await request.cancellation.is_cancelled()
        )

    @staticmethod
    async def _cancel_pending_tasks(pending: set[asyncio.Task[Any]]) -> None:
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task

    async def _answered_outcome(
        self,
        *,
        request: ControlAskRequest,
        ask: Any,
        state: _AskState,
        answer: Any,
    ) -> ControlAskOutcome:
        answer_text = str(answer) if answer is not None else ""
        async with self._store.user_content_operation(
            expected_generation=ask.clear_generation
        ):
            closed_ask = await self._store.close_ask(
                state.sid,
                request_id=ask.request_id,
                expected_generation=ask.clear_generation,
                answer=answer_text,
                resolution="user",
            )
            if closed_ask is not None:
                await self._publish_answered(
                    request=request,
                    ask=closed_ask,
                    answer_text=answer_text,
                    is_background=state.is_background,
                )
        await self._resume_background(bg_task_id=state.bg_task_id, manager=state.manager)
        logger.info(
            "ask_user_question.answered",
            session_id=state.sid,
            request_id=ask.request_id,
            length=len(answer_text),
        )
        if state.is_background:
            await self._publish_background_resumed(
                request=request,
                request_id=ask.request_id,
            )
        return ControlAskOutcome(
            answered=True,
            answer=answer_text,
            resolution="user",
            timed_out=False,
        )

    async def _publish_answered(
        self,
        *,
        request: ControlAskRequest,
        ask: Any,
        answer_text: str,
        is_background: bool,
    ) -> None:
        try:
            await control_events.publish_control_ask_answered(
                session_id=request.session_id,
                user_id=request.user_id,
                turn_id=request.turn_id,
                ask=ask,
                answer=answer_text,
                background=is_background,
            )
        except Exception:
            logger.debug("ask_user_question.persist_response_failed", exc_info=True)

    @staticmethod
    async def _publish_background_resumed(
        *,
        request: ControlAskRequest,
        request_id: str,
    ) -> None:
        try:
            await control_events.publish_control_event(
                "control.background.resumed",
                {
                    "session_id": request.session_id,
                    "request_id": request_id,
                },
                session_id=request.session_id,
                turn_id=request.turn_id,
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("ask_user_question.resume_event_failed", exc_info=True)

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
                await manager.suspend_waiting_user(bg_task_id, reason="awaiting_user_answer")
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
                    "expires_at_ms": (int(ask.expires_at * 1000) if ask.expires_at else None),
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
        async with self._store.user_content_operation(
            expected_generation=ask.clear_generation
        ):
            closed_ask = await self._store.close_ask(
                request.session_id,
                request_id=ask.request_id,
                expected_generation=ask.clear_generation,
                answer=None,
                resolution="cancelled",
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
                    logger.debug(
                        "ask_user_question.persist_cancelled_failed",
                        exc_info=True,
                    )
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
        ask: Any,
        is_background: bool,
        bg_task_id: str | None,
        manager: Any,
    ) -> None:
        async with self._store.user_content_operation(
            expected_generation=ask.clear_generation
        ):
            closed_ask = await self._store.close_ask(
                request.session_id,
                request_id=ask.request_id,
                expected_generation=ask.clear_generation,
                answer=None,
                resolution="timeout",
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
                    logger.debug(
                        "ask_user_question.persist_timeout_failed",
                        exc_info=True,
                    )
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
