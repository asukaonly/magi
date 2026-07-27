"""Runtime-scoped admission and processing for accepted conversation outcomes."""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

from magi.config import get_config
from magi.core.logger import get_logger
from magi.core.sqlite import sqlite_connection_async
from magi.memory.l0.attention import (
    AttentionActionType,
    AttentionKind,
    AttentionUpdateAction,
)
from magi.memory.l0.attention_update_scheduler import (
    AcceptedL0AttentionTurn,
    AttentionBatch,
    L0AttentionUpdateScheduler,
)
from magi.memory.l0.working.source_forgetting import (
    forgotten_attention_source_references,
    forgotten_attention_turn_cutoffs,
)
from magi.memory.source_event_governance import (
    chat_session_source_reference,
    latest_post_turn_forget_cutoff,
)
from magi.personality.feature_flags import get_personality_feature_flags
from magi.personality.interaction_batch_analyzer import (
    BatchInteractionAnalysis,
    analyze_interaction_batch,
)
from magi.personality.interaction_observation_router import (
    apply_interaction_observations,
)

logger = get_logger(__name__)

_PROCESSED_OUTCOME_DEDUPE_LIMIT = 8192
_TERMINAL_TASK_BARRIER_LIMIT = 4096
_REVOKED_SOURCE_CUTOFF_LIMIT = 8192
_MAX_CONCURRENT_ANALYSES = 2


@dataclass(frozen=True, slots=True)
class AcceptedConversationOutcome:
    """One durable conversation outcome admitted to shared understanding."""

    outcome_id: str
    source_turn_id: str
    user_id: str
    session_id: str
    user_message: str
    assistant_response: str
    epoch: int
    accepted_at: float
    persona_id: str | None = None
    incoming_fact_kind: str | None = None
    execution_mode: str | None = None
    task_id: str | None = None
    task_attempt: int | None = None
    delivery_attempt_no: int | None = None
    source_message_ids: tuple[str, ...] = ()
    apply_personality: bool = True
    immediate: bool = False


@dataclass(frozen=True, slots=True)
class AcceptedBackgroundCompletion:
    """One durable terminal background-task message eligible for L0 closure."""

    outcome_id: str
    source_turn_id: str | None
    user_id: str
    session_id: str
    task_id: str
    task_status: str
    response_text: str
    accepted_at: float
    task_attempt: int = 0


@dataclass(frozen=True, slots=True)
class AcceptedBackgroundAttempt:
    """One durably started background-task attempt eligible to reopen L0."""

    outcome_id: str
    source_turn_id: str | None
    user_id: str
    session_id: str
    task_id: str
    task_attempt: int
    accepted_at: float


@dataclass(frozen=True, slots=True)
class _InteractionRequest:
    user_id: str
    user_message: str
    response_text: str
    incoming_fact_kind: str | None
    execution_mode: str | None
    session_id: str
    source_turn_id: str
    persona_id: str | None


class PostTurnUnderstandingService:
    """Own one runtime-wide scheduler for accepted conversation outcomes."""

    def __init__(
        self,
        *,
        unified_memory: Any,
        self_memory: Any,
    ) -> None:
        self._unified_memory = unified_memory
        self._self_memory = self_memory
        self._outcomes: dict[str, AcceptedConversationOutcome] = {}
        self._processed_outcome_ids: set[str] = set()
        self._processed_outcome_order: deque[str] = deque()
        self._pending_direct_ids: set[str] = set()
        self._terminal_task_keys: set[tuple[str, str, int]] = set()
        self._terminal_task_order: deque[tuple[str, str, int]] = deque()
        self._latest_task_attempts: dict[tuple[str, str], int] = {}
        self._latest_task_order: deque[tuple[str, str]] = deque()
        self._revoked_source_cutoffs: dict[tuple[str, str], float] = {}
        self._revoked_source_order: deque[tuple[str, str]] = deque()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_lock_users: dict[str, int] = {}
        self._session_registry_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._analysis_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ANALYSES)
        self._scheduler = self._build_scheduler()

    @property
    def scheduler(self) -> L0AttentionUpdateScheduler | None:
        """Expose the shared scheduler for runtime observability and tests."""

        return self._scheduler

    async def admit(self, outcome: AcceptedConversationOutcome) -> bool:
        """Admit one accepted outcome using its stable outcome identity."""

        normalized = _normalize_outcome(outcome)
        if normalized is None or self._scheduler is None:
            return False
        async with self._admission_lock:
            if (
                normalized.outcome_id in self._outcomes
                or normalized.outcome_id in self._processed_outcome_ids
                or self._outcome_is_revoked_locked(normalized)
            ):
                return False
            self._remember_task_attempt_locked(normalized)
            self._outcomes[normalized.outcome_id] = normalized
            queued = await self._scheduler.enqueue(
                AcceptedL0AttentionTurn(
                    user_id=normalized.user_id,
                    session_id=normalized.session_id,
                    turn_id=normalized.outcome_id,
                    user_message=normalized.user_message,
                    assistant_response=normalized.assistant_response,
                    epoch=normalized.epoch,
                    accepted_at=normalized.accepted_at,
                    persona_id=normalized.persona_id,
                    incoming_fact_kind=normalized.incoming_fact_kind,
                    execution_mode=normalized.execution_mode,
                    immediate=normalized.immediate,
                )
            )
            if not queued:
                self._outcomes.pop(normalized.outcome_id, None)
            return queued

    async def admit_background_completion(
        self,
        completion: AcceptedBackgroundCompletion,
    ) -> bool:
        """Close task-linked L0 attention after a terminal message is durable."""

        normalized = _normalize_completion(completion)
        if normalized is None:
            return False
        expected_epoch = self._current_memory_epoch()

        terminal_key = (
            normalized.session_id,
            normalized.task_id,
            normalized.task_attempt,
        )
        async with self._admission_lock:
            if (
                normalized.outcome_id in self._processed_outcome_ids
                or normalized.outcome_id in self._pending_direct_ids
            ):
                return False
            self._pending_direct_ids.add(normalized.outcome_id)
            self._remember_terminal_task_locked(terminal_key)
            self._remember_latest_task_attempt_locked(
                normalized.session_id,
                normalized.task_id,
                normalized.task_attempt,
            )

        try:
            await self._resolve_terminal_attention(
                normalized,
                expected_epoch=expected_epoch,
            )
        except BaseException:
            async with self._admission_lock:
                self._pending_direct_ids.discard(normalized.outcome_id)
            raise

        async with self._admission_lock:
            self._pending_direct_ids.discard(normalized.outcome_id)
            self._remember_processed_outcome_locked(normalized.outcome_id)
        return True

    async def admit_background_attempt(
        self,
        attempt: AcceptedBackgroundAttempt,
    ) -> bool:
        """Reopen existing task attention for one durably started retry."""

        normalized = _normalize_background_attempt(attempt)
        if normalized is None:
            return False
        expected_epoch = self._current_memory_epoch()
        terminal_key = (
            normalized.session_id,
            normalized.task_id,
            normalized.task_attempt,
        )
        async with self._admission_lock:
            if (
                normalized.outcome_id in self._processed_outcome_ids
                or normalized.outcome_id in self._pending_direct_ids
            ):
                return False
            self._pending_direct_ids.add(normalized.outcome_id)
            self._remember_latest_task_attempt_locked(
                normalized.session_id,
                normalized.task_id,
                normalized.task_attempt,
            )
            already_terminal = terminal_key in self._terminal_task_keys

        try:
            if not already_terminal:
                await self._reopen_task_attention(
                    normalized,
                    expected_epoch=expected_epoch,
                )
        except BaseException:
            async with self._admission_lock:
                self._pending_direct_ids.discard(normalized.outcome_id)
            raise

        async with self._admission_lock:
            self._pending_direct_ids.discard(normalized.outcome_id)
            self._remember_processed_outcome_locked(normalized.outcome_id)
        return True

    async def discard_session(self, session_id: str) -> None:
        """Discard queued outcomes for one destructively cleared session."""

        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        async with self._admission_lock:
            scheduler = self._scheduler
            if scheduler is not None:
                await scheduler.discard_session(normalized_session_id)
            for outcome_id, outcome in tuple(self._outcomes.items()):
                if outcome.session_id == normalized_session_id:
                    self._outcomes.pop(outcome_id, None)
            for terminal_key in tuple(self._terminal_task_keys):
                if terminal_key[0] == normalized_session_id:
                    self._terminal_task_keys.discard(terminal_key)
            self._terminal_task_order = deque(
                key
                for key in self._terminal_task_order
                if key[0] != normalized_session_id
            )
            for task_key in tuple(self._latest_task_attempts):
                if task_key[0] == normalized_session_id:
                    self._latest_task_attempts.pop(task_key, None)
            self._latest_task_order = deque(
                key
                for key in self._latest_task_order
                if key[0] != normalized_session_id
            )
            for source_key in tuple(self._revoked_source_cutoffs):
                if source_key[0] == normalized_session_id:
                    self._revoked_source_cutoffs.pop(source_key, None)
            self._revoked_source_order = deque(
                key
                for key in self._revoked_source_order
                if key[0] != normalized_session_id
            )

    async def revoke_source_turns(
        self,
        *,
        session_id: str,
        source_turn_ids: tuple[str, ...] | list[str] | set[str],
        revoked_at: float | None = None,
    ) -> int:
        """Revoke accepted outcomes at or before one exact deletion boundary."""

        normalized_session_id = str(session_id or "").strip()
        normalized_turn_ids = tuple(
            dict.fromkeys(
                normalized
                for value in source_turn_ids
                if (normalized := str(value or "").strip())
            )
        )
        if not normalized_session_id or not normalized_turn_ids:
            return 0
        cutoff = _finite_positive_timestamp(revoked_at) or time.time()
        async with self._admission_lock:
            for turn_id in normalized_turn_ids:
                self._remember_revoked_source_locked(
                    normalized_session_id,
                    turn_id,
                    cutoff,
                )
            revoked_outcome_ids = {
                outcome_id
                for outcome_id, outcome in self._outcomes.items()
                if outcome.session_id == normalized_session_id
                and outcome.source_turn_id in normalized_turn_ids
                and outcome.accepted_at <= cutoff
            }
            scheduler = self._scheduler
            if scheduler is not None and revoked_outcome_ids:
                await scheduler.discard_turns(
                    normalized_session_id,
                    revoked_outcome_ids,
                )
        async with self._session_guard(normalized_session_id):
            return len(revoked_outcome_ids)

    async def shutdown(
        self,
        *,
        flush: bool = True,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Flush and close the runtime-wide scheduler."""

        scheduler = self._scheduler
        if scheduler is None:
            return True
        return await scheduler.shutdown(
            flush=flush,
            timeout_seconds=timeout_seconds,
        )

    def has_pending_work(self, session_id: str | None = None) -> bool:
        """Return whether the shared scheduler still has admitted work."""

        scheduler = self._scheduler
        if scheduler is None:
            return False
        return scheduler.has_pending_work(session_id=session_id)

    def _build_scheduler(self) -> L0AttentionUpdateScheduler | None:
        l0_store = getattr(self._unified_memory, "l0", None)
        if l0_store is None and self._self_memory is None:
            return None
        return L0AttentionUpdateScheduler(
            processor=self._process_batch,
            config_getter=self._attention_update_config,
            finalizer=self._finalize_outcomes,
        )

    def _attention_update_config(self) -> Any:
        getter = getattr(self._unified_memory, "_memory_config_getter", None)
        if callable(getter):
            return getter()
        return get_config().agent.memory

    async def _process_batch(self, batch: AttentionBatch) -> bool:
        if not batch:
            return True
        outcomes = tuple(
            self._outcomes.get(turn.turn_id)
            for turn in batch
        )
        if any(outcome is None for outcome in outcomes):
            logger.warning(
                "Accepted outcome metadata disappeared before analysis",
                session_id=batch[0].session_id,
            )
            return True
        typed_outcomes = tuple(
            outcome for outcome in outcomes if outcome is not None
        )
        session_id = typed_outcomes[0].session_id
        if any(outcome.session_id != session_id for outcome in typed_outcomes):
            logger.error("Shared post-turn batch mixed multiple sessions")
            return True

        return await self._process_serialized_batch(batch, typed_outcomes)

    async def _process_serialized_batch(
        self,
        batch: AttentionBatch,
        outcomes: tuple[AcceptedConversationOutcome, ...],
    ) -> bool:
        expected_epoch: int | None = None
        active_pairs = tuple(zip(batch, outcomes, strict=True))
        if self._unified_memory is not None:
            expected_epoch = int(self._unified_memory.memory_operation_epoch())
            active_pairs = tuple(
                pair for pair in active_pairs if int(pair[1].epoch) == expected_epoch
            )
            if not active_pairs:
                return True
        active_pairs = await self._exclude_forgotten_source_pairs(active_pairs)
        if not active_pairs:
            return True

        features = get_personality_feature_flags()
        personality_enabled = bool(
            features.state_memory_enabled or features.deep_persona_enabled
        )
        l0_store = getattr(self._unified_memory, "l0", None)
        if l0_store is None and not personality_enabled:
            return True

        session_id = active_pairs[0][1].session_id
        snapshot = (
            await l0_store.get_attention_snapshot(session_id)
            if l0_store is not None
            else {"revision": 0, "items": []}
        )
        forget_cutoff_at = _finite_positive_timestamp(
            snapshot.get("forget_cutoff_at")
        )
        if forget_cutoff_at is not None:
            active_pairs = tuple(
                pair
                for pair in active_pairs
                if float(pair[1].accepted_at) > forget_cutoff_at
            )
            if not active_pairs:
                return True

        active_batch = tuple(pair[0] for pair in active_pairs)
        active_outcomes = tuple(pair[1] for pair in active_pairs)
        milestone_conditions = await self._load_milestone_conditions(features)
        current_attention = list(snapshot.get("items") or [])
        async with self._analysis_semaphore:
            analysis = await analyze_interaction_batch(
                active_batch,
                current_attention=current_attention,
                milestone_conditions=milestone_conditions,
            )
        if analysis is None:
            return False

        if self._unified_memory is None:
            still_active = await self._exclude_forgotten_source_pairs(
                tuple(zip(active_batch, active_outcomes, strict=True))
            )
            if len(still_active) != len(active_pairs):
                return not still_active
            async with self._session_guard(session_id):
                return await self._apply_analysis(
                    batch=active_batch,
                    outcomes=active_outcomes,
                    analysis=analysis,
                    l0_store=l0_store,
                    expected_revision=int(snapshot.get("revision") or 0),
                    current_attention=current_attention,
                    personality_enabled=personality_enabled,
                    milestone_conditions=milestone_conditions,
                    expected_epoch=expected_epoch,
                )

        async with self._unified_memory.memory_operation_guard():
            async with self._session_guard(session_id):
                if (
                    expected_epoch is None
                    or int(self._unified_memory.memory_operation_epoch()) != expected_epoch
                ):
                    return True
                active_pairs = await self._exclude_forgotten_source_pairs(
                    tuple(zip(active_batch, active_outcomes, strict=True))
                )
                if len(active_pairs) != len(active_batch):
                    return not active_pairs
                return await self._apply_analysis(
                    batch=tuple(pair[0] for pair in active_pairs),
                    outcomes=tuple(pair[1] for pair in active_pairs),
                    analysis=analysis,
                    l0_store=l0_store,
                    expected_revision=int(snapshot.get("revision") or 0),
                    current_attention=current_attention,
                    personality_enabled=personality_enabled,
                    milestone_conditions=milestone_conditions,
                    expected_epoch=expected_epoch,
                )

    async def _apply_analysis(
        self,
        *,
        batch: AttentionBatch,
        outcomes: tuple[AcceptedConversationOutcome, ...],
        analysis: BatchInteractionAnalysis,
        l0_store: Any,
        expected_revision: int,
        current_attention: list[dict[str, Any]],
        personality_enabled: bool,
        milestone_conditions: dict[str, str] | None,
        expected_epoch: int | None,
    ) -> bool:
        active_outcome_ids = await self._active_conversation_outcome_ids(
            outcomes,
            expected_epoch=expected_epoch,
        )
        if len(active_outcome_ids) != len(outcomes):
            return not active_outcome_ids
        outcome_by_id = {outcome.outcome_id: outcome for outcome in outcomes}
        actions = self._bind_attention_actions(
            analysis.attention_actions,
            outcome_by_id=outcome_by_id,
            current_attention=current_attention,
        )
        if l0_store is not None:
            last_source_turn_id = outcomes[-1].source_turn_id
            updated_snapshot = await l0_store.apply_attention_actions(
                session_id=outcomes[0].session_id,
                user_id=outcomes[0].user_id,
                actions=actions,
                expected_revision=expected_revision,
                last_processed_turn_id=last_source_turn_id,
                source_texts=(outcome.user_message for outcome in outcomes),
                source_turn_accepted_at={
                    outcome.source_turn_id: outcome.accepted_at
                    for outcome in outcomes
                },
            )
            if updated_snapshot is None:
                logger.info(
                    "Retrying shared post-turn analysis after L0 revision changed",
                    session_id=outcomes[0].session_id,
                    first_outcome_id=outcomes[0].outcome_id,
                    last_outcome_id=outcomes[-1].outcome_id,
                    expected_revision=expected_revision,
                )
                return False

        if not personality_enabled:
            return True
        for outcome in outcomes:
            if (
                not outcome.apply_personality
                or outcome.outcome_id
                not in await self._active_conversation_outcome_ids(
                    (outcome,),
                    expected_epoch=expected_epoch,
                )
            ):
                continue
            request = _InteractionRequest(
                user_id=outcome.user_id,
                user_message=outcome.user_message,
                response_text=outcome.assistant_response,
                incoming_fact_kind=outcome.incoming_fact_kind,
                execution_mode=outcome.execution_mode,
                session_id=outcome.session_id,
                source_turn_id=outcome.source_turn_id,
                persona_id=outcome.persona_id,
            )
            turn_analysis = analysis.turn_analyses[outcome.outcome_id]
            await self._process_personality_turn_outcome(
                request,
                turn_analysis,
                milestone_conditions,
            )
            if (
                turn_analysis.memory_observations
                and outcome.outcome_id
                in await self._active_conversation_outcome_ids(
                    (outcome,),
                    expected_epoch=expected_epoch,
                )
            ):
                await self._apply_memory_observations(
                    request,
                    turn_analysis.memory_observations,
                )
        return True

    def _bind_attention_actions(
        self,
        actions: tuple[AttentionUpdateAction, ...],
        *,
        outcome_by_id: dict[str, AcceptedConversationOutcome],
        current_attention: list[dict[str, Any]],
    ) -> tuple[AttentionUpdateAction, ...]:
        current_by_id = {
            str(item.get("item_id") or ""): item
            for item in current_attention
            if str(item.get("item_id") or "")
        }
        bound: list[AttentionUpdateAction] = []
        for action in actions:
            sources = tuple(
                outcome_by_id[outcome_id]
                for outcome_id in action.source_turn_ids
                if outcome_id in outcome_by_id
            )
            source_turn_ids = tuple(
                dict.fromkeys(
                    outcome.source_turn_id
                    for outcome in sources
                    if outcome.source_turn_id
                )
            )
            if not source_turn_ids:
                continue
            source_task_ids = {
                outcome.task_id
                for outcome in sources
                if outcome.task_id
            }
            source_task_attempts = {
                outcome.task_attempt
                for outcome in sources
                if outcome.task_attempt is not None
            }
            target = current_by_id.get(str(action.target_item_id or ""))
            target_task_id = str((target or {}).get("task_id") or "").strip() or None
            target_task_attempt = _item_task_attempt(target)
            source_opens_task_loop = (
                target is None
                and action.action is AttentionActionType.ADD
                and action.kind is AttentionKind.OPEN_LOOP
            )
            task_id = target_task_id
            task_attempt = target_task_attempt
            if source_opens_task_loop:
                task_id = (
                    next(iter(source_task_ids))
                    if len(source_task_ids) == 1
                    else None
                )
                task_attempt = (
                    next(iter(source_task_attempts))
                    if len(source_task_attempts) == 1
                    else None
                )
            outcomes_session = sources[0].session_id if sources else None
            if (
                task_id
                and task_attempt is not None
                and outcomes_session is not None
            ):
                task_attempt = max(
                    task_attempt,
                    self._latest_task_attempts.get(
                        (outcomes_session, task_id),
                        task_attempt,
                    ),
                )
            rebound = replace(
                action,
                source_turn_ids=source_turn_ids,
                source_event_ids=(),
                task_id=task_id,
                task_attempt=task_attempt,
            )
            if (
                task_id
                and task_attempt is not None
                and outcomes_session is not None
                and (
                    (
                        outcomes_session,
                        task_id,
                        task_attempt,
                    ) in self._terminal_task_keys
                    or task_attempt
                    < self._latest_task_attempts.get(
                        (outcomes_session, task_id),
                        task_attempt,
                    )
                )
                and rebound.action is not AttentionActionType.RESOLVE
            ):
                continue
            bound.append(rebound)
        return tuple(bound)

    async def _resolve_terminal_attention(
        self,
        completion: AcceptedBackgroundCompletion,
        *,
        expected_epoch: int | None,
    ) -> None:
        l0_store = getattr(self._unified_memory, "l0", None)
        if l0_store is None:
            return
        if self._unified_memory is None:
            async with self._session_guard(completion.session_id):
                if not await self._direct_outcome_is_active(
                    completion,
                    expected_epoch=expected_epoch,
                ):
                    return
                await self._apply_terminal_resolution(l0_store, completion)
                checkpoint = getattr(l0_store, "checkpoint_session", None)
                if callable(checkpoint):
                    await checkpoint(completion.session_id)
        else:
            async with self._unified_memory.memory_operation_guard():
                async with self._session_guard(completion.session_id):
                    if not await self._direct_outcome_is_active(
                        completion,
                        expected_epoch=expected_epoch,
                    ):
                        return
                    await self._apply_terminal_resolution(l0_store, completion)
                    checkpoint = getattr(l0_store, "checkpoint_session", None)
                    if callable(checkpoint):
                        await checkpoint(completion.session_id)

    async def _apply_terminal_resolution(
        self,
        l0_store: Any,
        completion: AcceptedBackgroundCompletion,
    ) -> None:
        for _attempt in range(3):
            snapshot = await l0_store.get_attention_snapshot(completion.session_id)
            actions = _terminal_resolution_actions(completion, snapshot)
            if not actions:
                return
            updated = await l0_store.apply_attention_actions(
                session_id=completion.session_id,
                user_id=completion.user_id,
                actions=actions,
                expected_revision=int(snapshot.get("revision") or 0),
                last_processed_turn_id=(
                    completion.source_turn_id or completion.outcome_id
                ),
                source_texts=(),
                source_turn_accepted_at={},
            )
            if updated is not None:
                return
        raise RuntimeError("L0 background completion conflicted repeatedly")

    async def _reopen_task_attention(
        self,
        attempt: AcceptedBackgroundAttempt,
        *,
        expected_epoch: int | None,
    ) -> None:
        l0_store = getattr(self._unified_memory, "l0", None)
        if l0_store is None:
            return
        if self._unified_memory is None:
            async with self._session_guard(attempt.session_id):
                if not await self._attempt_can_reopen(
                    attempt,
                    expected_epoch=expected_epoch,
                ):
                    return
                await self._apply_attempt_reopen(l0_store, attempt)
                checkpoint = getattr(l0_store, "checkpoint_session", None)
                if callable(checkpoint):
                    await checkpoint(attempt.session_id)
        else:
            async with self._unified_memory.memory_operation_guard():
                async with self._session_guard(attempt.session_id):
                    if not await self._attempt_can_reopen(
                        attempt,
                        expected_epoch=expected_epoch,
                    ):
                        return
                    await self._apply_attempt_reopen(l0_store, attempt)
                    checkpoint = getattr(l0_store, "checkpoint_session", None)
                    if callable(checkpoint):
                        await checkpoint(attempt.session_id)

    async def _apply_attempt_reopen(
        self,
        l0_store: Any,
        attempt: AcceptedBackgroundAttempt,
    ) -> None:
        for _attempt in range(3):
            snapshot = await l0_store.get_attention_snapshot(attempt.session_id)
            action = _attempt_reopen_action(attempt, snapshot)
            if action is None:
                return
            updated = await l0_store.apply_attention_actions(
                session_id=attempt.session_id,
                user_id=attempt.user_id,
                actions=(action,),
                expected_revision=int(snapshot.get("revision") or 0),
                last_processed_turn_id=(
                    attempt.source_turn_id or attempt.outcome_id
                ),
                source_texts=(),
                source_turn_accepted_at={},
            )
            if updated is not None:
                return
        raise RuntimeError("L0 background attempt conflicted repeatedly")

    async def _attempt_can_reopen(
        self,
        attempt: AcceptedBackgroundAttempt,
        *,
        expected_epoch: int | None,
    ) -> bool:
        terminal_key = (
            attempt.session_id,
            attempt.task_id,
            attempt.task_attempt,
        )
        if terminal_key in self._terminal_task_keys:
            return False
        return await self._direct_outcome_is_active(
            attempt,
            expected_epoch=expected_epoch,
        )

    async def _direct_outcome_is_active(
        self,
        outcome: AcceptedBackgroundAttempt | AcceptedBackgroundCompletion,
        *,
        expected_epoch: int | None,
    ) -> bool:
        """Check direct task-lifecycle updates at their serialization point."""

        if expected_epoch is not None and not self._memory_epoch_matches(
            expected_epoch
        ):
            return False
        l0_store = getattr(self._unified_memory, "l0", None)
        database_path = str(
            getattr(self._unified_memory, "memory_db_path", "")
            or getattr(l0_store, "checkpoint_db_path", "")
            or ""
        ).strip()
        if not database_path:
            return True
        source_turn_id = str(outcome.source_turn_id or "").strip()
        references = [source_turn_id]
        if outcome.user_id and outcome.session_id:
            references.append(
                chat_session_source_reference(
                    user_id=outcome.user_id,
                    session_id=outcome.session_id,
                )
            )
        async with sqlite_connection_async(database_path) as db:
            permanently_forgotten = await forgotten_attention_source_references(
                db,
                references,
            )
            turn_cutoffs = await forgotten_attention_turn_cutoffs(
                db,
                (source_turn_id,),
            )
            global_forget_cutoff = await latest_post_turn_forget_cutoff(db)
        if expected_epoch is not None and not self._memory_epoch_matches(
            expected_epoch
        ):
            return False
        return bool(
            not permanently_forgotten
            and source_turn_id not in turn_cutoffs
            and outcome.accepted_at > global_forget_cutoff
        )

    async def _load_milestone_conditions(
        self,
        features: Any,
    ) -> dict[str, str] | None:
        if self._self_memory is None or not features.deep_persona_enabled:
            return None
        try:
            config = await self._self_memory.get_core_personality()
        except Exception:
            return None
        if not hasattr(config, "milestone_conditions"):
            return None
        return config.milestone_conditions or None

    async def _process_personality_turn_outcome(
        self,
        request: _InteractionRequest,
        analysis: Any,
        milestone_conditions: dict[str, str] | None,
    ) -> bool:
        if self._self_memory is None:
            return False
        try:
            return bool(
                await self._self_memory.process_turn_outcome(
                    user_id=request.user_id,
                    user_message=request.user_message,
                    analysis=analysis,
                    milestone_conditions=milestone_conditions,
                )
            )
        except Exception as exc:
            logger.warning("Failed to process turn outcome: %s", exc)
            return False

    async def _apply_memory_observations(
        self,
        request: _InteractionRequest,
        observations: list[Any],
    ) -> bool:
        try:
            return bool(
                await apply_interaction_observations(
                    observations=observations,
                    user_id=request.user_id,
                    user_message=request.user_message,
                    unified_memory=self._unified_memory,
                    self_memory=self._self_memory,
                    persona_id=request.persona_id,
                    session_id=request.session_id,
                    turn_id=request.source_turn_id,
                )
            )
        except Exception as exc:
            logger.warning("Failed to apply interaction observations: %s", exc)
            return False

    async def _exclude_forgotten_source_pairs(
        self,
        pairs: tuple[
            tuple[AcceptedL0AttentionTurn, AcceptedConversationOutcome],
            ...,
        ],
    ) -> tuple[
        tuple[AcceptedL0AttentionTurn, AcceptedConversationOutcome],
        ...,
    ]:
        if not pairs:
            return ()
        active_outcome_ids = await self._active_conversation_outcome_ids(
            tuple(pair[1] for pair in pairs),
            expected_epoch=None,
        )
        return tuple(
            pair for pair in pairs if pair[1].outcome_id in active_outcome_ids
        )

    async def _active_conversation_outcome_ids(
        self,
        outcomes: tuple[AcceptedConversationOutcome, ...],
        *,
        expected_epoch: int | None,
    ) -> set[str]:
        """Return outcomes still allowed by runtime and durable barriers."""

        if expected_epoch is not None and not self._memory_epoch_matches(
            expected_epoch
        ):
            return set()
        outcomes = tuple(
            outcome
            for outcome in outcomes
            if not self._outcome_is_revoked(outcome)
        )
        if not outcomes:
            return set()
        l0_store = getattr(self._unified_memory, "l0", None)
        database_path = str(
            getattr(self._unified_memory, "memory_db_path", "")
            or getattr(l0_store, "checkpoint_db_path", "")
            or ""
        ).strip()
        if not database_path:
            return {outcome.outcome_id for outcome in outcomes}
        source_references = tuple(
            dict.fromkeys(
                reference
                for outcome in outcomes
                for reference in (
                    outcome.source_turn_id,
                    *outcome.source_message_ids,
                    *(
                        (
                            chat_session_source_reference(
                                user_id=outcome.user_id,
                                session_id=outcome.session_id,
                            ),
                        )
                        if outcome.user_id and outcome.session_id
                        else ()
                    ),
                )
                if reference
            )
        )
        async with sqlite_connection_async(database_path) as db:
            permanently_forgotten = await forgotten_attention_source_references(
                db,
                source_references,
            )
            turn_cutoffs = await forgotten_attention_turn_cutoffs(
                db,
                (outcome.source_turn_id for outcome in outcomes),
            )
            global_forget_cutoff = await latest_post_turn_forget_cutoff(db)
        if expected_epoch is not None and not self._memory_epoch_matches(
            expected_epoch
        ):
            return set()
        if (
            not permanently_forgotten
            and not turn_cutoffs
            and global_forget_cutoff <= 0
        ):
            return {outcome.outcome_id for outcome in outcomes}
        return {
            outcome.outcome_id
            for outcome in outcomes
            if not permanently_forgotten.intersection(
                {
                    outcome.source_turn_id,
                    *outcome.source_message_ids,
                    *(
                        (
                            chat_session_source_reference(
                                user_id=outcome.user_id,
                                session_id=outcome.session_id,
                            ),
                        )
                        if outcome.user_id and outcome.session_id
                        else ()
                    ),
                }
            )
            and (
                outcome.source_turn_id not in turn_cutoffs
                or outcome.accepted_at
                > turn_cutoffs[outcome.source_turn_id]
            )
            and outcome.accepted_at > global_forget_cutoff
        }

    def _current_memory_epoch(self) -> int | None:
        if self._unified_memory is None:
            return None
        getter = getattr(self._unified_memory, "memory_operation_epoch", None)
        return int(getter()) if callable(getter) else None

    def _memory_epoch_matches(self, expected_epoch: int) -> bool:
        current_epoch = self._current_memory_epoch()
        return current_epoch is None or current_epoch == int(expected_epoch)

    def _finalize_outcomes(self, batch: AttentionBatch) -> None:
        for turn in batch:
            self._outcomes.pop(turn.turn_id, None)
            self._remember_processed_outcome_locked(turn.turn_id)

    def _remember_processed_outcome_locked(self, outcome_id: str) -> None:
        if outcome_id in self._processed_outcome_ids:
            return
        self._processed_outcome_ids.add(outcome_id)
        self._processed_outcome_order.append(outcome_id)
        while len(self._processed_outcome_order) > _PROCESSED_OUTCOME_DEDUPE_LIMIT:
            expired = self._processed_outcome_order.popleft()
            self._processed_outcome_ids.discard(expired)

    def _remember_task_attempt_locked(
        self,
        outcome: AcceptedConversationOutcome,
    ) -> None:
        if outcome.task_id is None or outcome.task_attempt is None:
            return
        self._remember_latest_task_attempt_locked(
            outcome.session_id,
            outcome.task_id,
            outcome.task_attempt,
        )

    def _remember_latest_task_attempt_locked(
        self,
        session_id: str,
        task_id: str,
        task_attempt: int,
    ) -> None:
        key = (session_id, task_id)
        current = self._latest_task_attempts.get(key)
        if current is not None and current >= task_attempt:
            return
        self._latest_task_attempts[key] = task_attempt
        if key not in self._latest_task_order:
            self._latest_task_order.append(key)
        while len(self._latest_task_order) > _TERMINAL_TASK_BARRIER_LIMIT:
            expired = self._latest_task_order.popleft()
            self._latest_task_attempts.pop(expired, None)

    def _remember_revoked_source_locked(
        self,
        session_id: str,
        source_turn_id: str,
        cutoff: float,
    ) -> None:
        key = (session_id, source_turn_id)
        current = self._revoked_source_cutoffs.get(key)
        self._revoked_source_cutoffs[key] = max(current or 0.0, cutoff)
        if key not in self._revoked_source_order:
            self._revoked_source_order.append(key)
        while len(self._revoked_source_order) > _REVOKED_SOURCE_CUTOFF_LIMIT:
            expired = self._revoked_source_order.popleft()
            self._revoked_source_cutoffs.pop(expired, None)

    def _outcome_is_revoked_locked(
        self,
        outcome: AcceptedConversationOutcome,
    ) -> bool:
        cutoff = self._revoked_source_cutoffs.get(
            (outcome.session_id, outcome.source_turn_id)
        )
        return cutoff is not None and outcome.accepted_at <= cutoff

    def _outcome_is_revoked(
        self,
        outcome: AcceptedConversationOutcome,
    ) -> bool:
        return self._outcome_is_revoked_locked(outcome)

    def _remember_terminal_task_locked(
        self,
        key: tuple[str, str, int],
    ) -> None:
        if key in self._terminal_task_keys:
            return
        self._terminal_task_keys.add(key)
        self._terminal_task_order.append(key)
        while len(self._terminal_task_order) > _TERMINAL_TASK_BARRIER_LIMIT:
            expired = self._terminal_task_order.popleft()
            self._terminal_task_keys.discard(expired)

    @asynccontextmanager
    async def _session_guard(self, session_id: str):
        async with self._session_registry_lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            self._session_lock_users[session_id] = (
                self._session_lock_users.get(session_id, 0) + 1
            )
        acquired = False
        try:
            await lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()
            async with self._session_registry_lock:
                remaining = self._session_lock_users.get(session_id, 1) - 1
                if remaining <= 0:
                    self._session_lock_users.pop(session_id, None)
                    if self._session_locks.get(session_id) is lock:
                        self._session_locks.pop(session_id, None)
                else:
                    self._session_lock_users[session_id] = remaining


def _normalize_outcome(
    outcome: AcceptedConversationOutcome,
) -> AcceptedConversationOutcome | None:
    outcome_id = str(outcome.outcome_id or "").strip()
    source_turn_id = str(outcome.source_turn_id or "").strip()
    session_id = str(outcome.session_id or "").strip()
    if not outcome_id or not source_turn_id or not session_id:
        return None
    accepted_at = _finite_positive_timestamp(outcome.accepted_at) or time.time()
    task_id = str(outcome.task_id or "").strip() or None
    task_attempt = _nonnegative_int(outcome.task_attempt)
    if task_id is not None and task_attempt is None:
        task_attempt = 0
    return replace(
        outcome,
        outcome_id=outcome_id,
        source_turn_id=source_turn_id,
        user_id=str(outcome.user_id or "").strip(),
        session_id=session_id,
        accepted_at=accepted_at,
        task_id=task_id,
        task_attempt=task_attempt,
        delivery_attempt_no=_nonnegative_int(outcome.delivery_attempt_no),
        source_message_ids=tuple(
            dict.fromkeys(
                normalized
                for value in outcome.source_message_ids
                if (normalized := str(value or "").strip())
            )
        ),
    )


def _normalize_completion(
    completion: AcceptedBackgroundCompletion,
) -> AcceptedBackgroundCompletion | None:
    outcome_id = str(completion.outcome_id or "").strip()
    session_id = str(completion.session_id or "").strip()
    task_id = str(completion.task_id or "").strip()
    task_status = str(completion.task_status or "").strip().lower()
    if (
        not outcome_id
        or not session_id
        or not task_id
        or task_status not in {"succeeded", "failed", "cancelled"}
    ):
        return None
    task_attempt = _nonnegative_int(completion.task_attempt)
    return replace(
        completion,
        outcome_id=outcome_id,
        source_turn_id=(
            str(completion.source_turn_id or "").strip() or None
        ),
        user_id=str(completion.user_id or "").strip(),
        session_id=session_id,
        task_id=task_id,
        task_status=task_status,
        accepted_at=(
            _finite_positive_timestamp(completion.accepted_at) or time.time()
        ),
        task_attempt=task_attempt if task_attempt is not None else 0,
    )


def _normalize_background_attempt(
    attempt: AcceptedBackgroundAttempt,
) -> AcceptedBackgroundAttempt | None:
    outcome_id = str(attempt.outcome_id or "").strip()
    session_id = str(attempt.session_id or "").strip()
    task_id = str(attempt.task_id or "").strip()
    task_attempt = _nonnegative_int(attempt.task_attempt)
    if (
        not outcome_id
        or not session_id
        or not task_id
        or task_attempt is None
    ):
        return None
    return replace(
        attempt,
        outcome_id=outcome_id,
        source_turn_id=(
            str(attempt.source_turn_id or "").strip() or None
        ),
        user_id=str(attempt.user_id or "").strip(),
        session_id=session_id,
        task_id=task_id,
        task_attempt=task_attempt,
        accepted_at=(
            _finite_positive_timestamp(attempt.accepted_at) or time.time()
        ),
    )


def _terminal_resolution_actions(
    completion: AcceptedBackgroundCompletion,
    snapshot: dict[str, Any],
) -> tuple[AttentionUpdateAction, ...]:
    items = list(snapshot.get("items") or [])
    targets = [
        item
        for item in items
        if str(item.get("task_id") or "").strip() == completion.task_id
        and _item_task_attempt(item) <= completion.task_attempt
    ]
    return tuple(
        AttentionUpdateAction(
            action=AttentionActionType.RESOLVE,
            target_item_id=str(item.get("item_id") or "").strip(),
            task_id=completion.task_id,
            task_attempt=completion.task_attempt,
        )
        for item in targets
        if str(item.get("item_id") or "").strip()
        and str(item.get("status") or "") in {"active", "background"}
    )


def _attempt_reopen_action(
    attempt: AcceptedBackgroundAttempt,
    snapshot: dict[str, Any],
) -> AttentionUpdateAction | None:
    candidates = [
        item
        for item in snapshot.get("items") or ()
        if str(item.get("task_id") or "").strip() == attempt.task_id
        and _item_task_attempt(item) < attempt.task_attempt
    ]
    if not candidates:
        return None
    target = max(
        candidates,
        key=lambda item: (
            _item_task_attempt(item),
            float(item.get("last_reinforced_at") or 0.0),
        ),
    )
    target_id = str(target.get("item_id") or "").strip()
    if not target_id:
        return None
    return AttentionUpdateAction(
        action=AttentionActionType.REINFORCE,
        target_item_id=target_id,
        task_id=attempt.task_id,
        task_attempt=attempt.task_attempt,
    )


def _item_task_attempt(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    value = item.get("task_attempt")
    if value is None:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("task_attempt")
    normalized = _nonnegative_int(value)
    return normalized if normalized is not None else 0


def _finite_positive_timestamp(value: Any) -> float | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0 or not math.isfinite(timestamp):
        return None
    return timestamp


def _nonnegative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


__all__ = [
    "AcceptedBackgroundAttempt",
    "AcceptedBackgroundCompletion",
    "AcceptedConversationOutcome",
    "PostTurnUnderstandingService",
]
