"""Retry-safe projection and deletion workflows for manual entries."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, TypeVar

from .l1_projector import ManualEntryProjectionGovernedError
from .models import ManualEntry

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _memory_guarded(
    method: Callable[
        Concatenate["ManualEntryWorkflow", _P],
        Awaitable[_R],
    ],
) -> Callable[
    Concatenate["ManualEntryWorkflow", _P],
    Awaitable[_R],
]:
    """Keep one cross-store workflow indivisible from an exclusive clear."""

    @wraps(method)
    async def guarded(
        self: "ManualEntryWorkflow",
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        async with self._memory_operation_guard():
            return await method(self, *args, **kwargs)

    return guarded


class ManualEntryWorkflowError(RuntimeError):
    """Base error for a retryable manual-entry workflow failure."""


class ManualEntryProjectionError(ManualEntryWorkflowError):
    """The L1 projection could not be durably linked."""


class ManualEntryGovernanceRejectedError(ManualEntryProjectionError):
    """A durable user-forget rule rejected the source occurrence."""

    def __init__(
        self,
        reason: str,
        *,
        source_preserved: bool = False,
    ) -> None:
        super().__init__("Manual-entry projection is blocked by memory governance")
        self.reason = str(reason or "source_reference")
        self.source_preserved = bool(source_preserved)
        self.retry_as_new = not self.source_preserved


class ManualEntryCleanupError(ManualEntryWorkflowError):
    """Owned memory projections could not be fully removed."""


class ManualEntryDeletionInProgressError(ManualEntryWorkflowError):
    """A projection repair was attempted after deletion was gated."""


class ManualEntryNotFoundError(ManualEntryWorkflowError):
    """The requested source row does not exist."""


class ManualEntryDeleteStartError(ManualEntryWorkflowError):
    """The durable delete gate could not be established."""


class ManualEntryDeleteConflictError(ManualEntryWorkflowError):
    """The source row changed while deletion was being advanced."""


class ManualEntryDeleteCompletionError(ManualEntryWorkflowError):
    """The source row could not be finalized after cleanup."""


@dataclass(frozen=True, slots=True)
class ManualEntryDeleteResult:
    """Result of an idempotent manual-entry deletion."""

    already_deleted: bool = False


def normalized_event_id(value: str | None) -> str | None:
    """Return a non-empty event identity or ``None``."""
    return str(value or "").strip() or None


def projection_recovery_required(entry: ManualEntry) -> bool:
    """Return whether an active source row needs startup recovery."""
    return bool(
        entry.deleted_at is None
        and (
            entry.delete_requested_at is not None
            or normalized_event_id(entry.pending_l1_event_id) is not None
            or normalized_event_id(entry.l1_event_id) is None
        )
    )


class ManualEntryWorkflow:
    """Advance cross-database manual-entry work without HTTP dependencies."""

    def __init__(
        self,
        *,
        store: Any,
        projector: Any,
        memory: Any,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._projector = projector
        self._memory = memory
        self._clock = clock

    async def load_projection_state(self, entry_id: str) -> ManualEntry:
        """Reload a source row or raise a retryable projection failure."""
        try:
            current = await self._store.get(entry_id)
        except Exception as exc:
            raise ManualEntryProjectionError("Could not load projection state") from exc
        if current is None:
            raise ManualEntryProjectionError("Projection source row is missing")
        return current

    @_memory_guarded
    async def forget_event_ids(
        self,
        *,
        event_ids: list[str],
        reason: str,
        block_source_item: bool,
    ) -> None:
        """Remove known or merely reserved event identities across all layers."""
        normalized = list(
            dict.fromkeys(
                event_id
                for event_id in (normalized_event_id(value) for value in event_ids)
                if event_id is not None
            )
        )
        if not normalized:
            return
        if self._memory is None or getattr(self._memory, "l1", None) is None:
            raise ManualEntryCleanupError("Memory L1 store is unavailable")
        try:
            await self._memory.forget_known_source_events(
                normalized,
                reason=reason,
                block_source_item=block_source_item,
            )
        except Exception as exc:
            raise ManualEntryCleanupError("Memory cleanup did not complete") from exc

    @_memory_guarded
    async def forget_owned_projections(
        self,
        *,
        entry: ManualEntry,
        reason: str,
        block_source_item: bool,
    ) -> str | None:
        """Forget every linked, pending, or reconstructable L1 identity."""
        predecessor_event_id = normalized_event_id(entry.l1_event_id)
        event_ids = [
            value
            for value in (
                predecessor_event_id,
                normalized_event_id(entry.pending_l1_event_id),
            )
            if value is not None
        ]
        try:
            pending_event_id = normalized_event_id(entry.pending_l1_event_id)
            should_reconstruct_candidate = (
                pending_event_id is not None or predecessor_event_id is None
            )
            if pending_event_id is None and predecessor_event_id is not None:
                if self._memory is None or getattr(self._memory, "l1", None) is None:
                    raise RuntimeError("Memory L1 store is unavailable")
                linked = await self._memory.l1.get_event(predecessor_event_id)
                should_reconstruct_candidate = (
                    linked is None or linked.get("deleted_at") is not None
                )
            if self._projector is not None and should_reconstruct_candidate:
                candidate_event_id = self._projector.event_id_for(
                    entry,
                    predecessor_event_id=(
                        normalized_event_id(entry.pending_l1_predecessor_event_id)
                        if entry.pending_l1_event_id is not None
                        else predecessor_event_id
                    ),
                )
                if candidate_event_id is not None:
                    event_ids.append(candidate_event_id)
        except Exception as exc:
            raise ManualEntryCleanupError("Could not reconstruct projection identity") from exc

        await self.forget_event_ids(
            event_ids=event_ids,
            reason=reason,
            block_source_item=block_source_item,
        )
        return predecessor_event_id

    @_memory_guarded
    async def project_and_link(
        self,
        *,
        entry: ManualEntry,
        predecessor_event_id: str | None,
        replacement_reason: str = "manual_entry_projection_replace",
    ) -> None:
        """Reserve, write, and complete one retry-safe cross-store projection."""
        if self._projector is None:
            raise ManualEntryProjectionError("Manual-entry projector is unavailable")

        normalized_predecessor = normalized_event_id(predecessor_event_id)
        if (
            entry.deleted_at is not None
            or entry.delete_requested_at is not None
            or normalized_event_id(entry.l1_event_id) != normalized_predecessor
        ):
            raise ManualEntryProjectionError("Projection source state changed")

        try:
            await self._projector.ensure_projectable(
                entry,
                predecessor_event_id=normalized_predecessor,
            )
        except ManualEntryProjectionGovernedError as exc:
            await self._finalize_governed_projection_rejection(
                entry,
                reason=exc.reason,
            )
            raise ManualEntryGovernanceRejectedError(exc.reason) from exc
        except Exception as exc:
            raise ManualEntryProjectionError(
                "Could not verify projection governance"
            ) from exc

        try:
            event_id = normalized_event_id(
                self._projector.event_id_for(
                    entry,
                    predecessor_event_id=normalized_predecessor,
                )
            )
        except Exception as exc:
            raise ManualEntryProjectionError("Could not derive projection identity") from exc
        if event_id is None:
            raise ManualEntryProjectionError("Projection identity is empty")

        pending_event_id = normalized_event_id(entry.pending_l1_event_id)
        pending_predecessor = normalized_event_id(entry.pending_l1_predecessor_event_id)
        if pending_event_id is not None and (
            pending_event_id != event_id or pending_predecessor != normalized_predecessor
        ):
            raise ManualEntryProjectionError("Reserved projection identity does not match")

        try:
            reserved = await self._store.reserve_l1_projection(
                entry.entry_id,
                event_id,
                expected_previous_event_id=normalized_predecessor,
            )
        except Exception as exc:
            current = await self.load_projection_state(entry.entry_id)
            if self._projection_is_complete(current, event_id=event_id):
                self._copy_projection_state(entry, current)
                return
            if not self._projection_is_reserved(
                current,
                event_id=event_id,
                predecessor_event_id=normalized_predecessor,
            ):
                raise ManualEntryProjectionError("Projection reservation failed") from exc
            self._copy_projection_state(entry, current)
        else:
            if not reserved:
                current = await self.load_projection_state(entry.entry_id)
                if self._projection_is_complete(current, event_id=event_id):
                    self._copy_projection_state(entry, current)
                    return
                if not self._projection_is_reserved(
                    current,
                    event_id=event_id,
                    predecessor_event_id=normalized_predecessor,
                ):
                    raise ManualEntryProjectionError("Projection reservation was rejected")
                self._copy_projection_state(entry, current)
            else:
                entry.pending_l1_event_id = event_id
                entry.pending_l1_predecessor_event_id = normalized_predecessor

        if normalized_predecessor is not None:
            await self.forget_event_ids(
                event_ids=[normalized_predecessor],
                reason=replacement_reason,
                block_source_item=False,
            )

        try:
            stored_event_id = normalized_event_id(
                await self._projector.project_current(
                    entry,
                    predecessor_event_id=normalized_predecessor,
                )
            )
        except ManualEntryProjectionGovernedError as exc:
            await self._finalize_governed_projection_rejection(
                entry,
                reason=exc.reason,
            )
            raise ManualEntryGovernanceRejectedError(exc.reason) from exc
        except Exception as exc:
            raise ManualEntryProjectionError("Projection write failed") from exc
        if stored_event_id is None:
            raise ManualEntryProjectionError("Projection write returned no identity")
        if stored_event_id != event_id:
            await self.forget_event_ids(
                event_ids=[stored_event_id, event_id],
                reason="manual_entry_projection_identity_mismatch",
                block_source_item=False,
            )
            raise ManualEntryProjectionError("Projection write returned a different identity")

        try:
            completed = await self._store.complete_l1_projection(
                entry.entry_id,
                event_id,
                expected_previous_event_id=normalized_predecessor,
            )
        except Exception as exc:
            current = await self.load_projection_state(entry.entry_id)
            if not self._projection_is_complete(current, event_id=event_id):
                if (
                    current.deleted_at is not None
                    or current.delete_requested_at is not None
                ):
                    governance_reason = (
                        await self._current_projection_governance_reason(
                            entry,
                            predecessor_event_id=normalized_predecessor,
                        )
                    )
                    await self._compensate_cancelled_projection(
                        current,
                        event_id,
                    )
                    raise ManualEntryGovernanceRejectedError(
                        governance_reason,
                    ) from exc
                await self._compensate_cancelled_projection(current, event_id)
                raise ManualEntryProjectionError("Projection link failed") from exc
            self._copy_projection_state(entry, current)
            return

        if not completed:
            current = await self.load_projection_state(entry.entry_id)
            if not self._projection_is_complete(current, event_id=event_id):
                if (
                    current.deleted_at is not None
                    or current.delete_requested_at is not None
                ):
                    governance_reason = (
                        await self._current_projection_governance_reason(
                            entry,
                            predecessor_event_id=normalized_predecessor,
                        )
                    )
                    await self._compensate_cancelled_projection(
                        current,
                        event_id,
                    )
                    raise ManualEntryGovernanceRejectedError(
                        governance_reason,
                    )
                await self._compensate_cancelled_projection(current, event_id)
                raise ManualEntryProjectionError("Projection link was rejected")
            self._copy_projection_state(entry, current)
            return

        entry.l1_event_id = event_id
        entry.pending_l1_event_id = None
        entry.pending_l1_predecessor_event_id = None

    @_memory_guarded
    async def replace_and_project(
        self,
        *,
        entry: ManualEntry,
        predecessor_event_id: str | None,
        reason: str,
    ) -> None:
        """Atomically reserve a replacement source snapshot, then project it."""
        if self._projector is None:
            raise ManualEntryProjectionError("Manual-entry projector is unavailable")

        normalized_predecessor = normalized_event_id(predecessor_event_id)
        if (
            entry.deleted_at is not None
            or entry.delete_requested_at is not None
            or normalized_event_id(entry.l1_event_id) != normalized_predecessor
        ):
            raise ManualEntryProjectionError("Replacement source state changed")
        try:
            event_id = normalized_event_id(
                self._projector.event_id_for(
                    entry,
                    predecessor_event_id=normalized_predecessor,
                )
            )
        except Exception as exc:
            raise ManualEntryProjectionError("Could not derive projection identity") from exc
        if event_id is None:
            raise ManualEntryProjectionError("Projection identity is empty")

        try:
            async with self._projector.governed_write_guard():
                await self._projector.ensure_projectable_guarded(
                    entry,
                    predecessor_event_id=normalized_predecessor,
                )
                try:
                    reserved = (
                        await self._store.replace_and_reserve_l1_projection(
                            entry,
                            event_id,
                            expected_previous_event_id=normalized_predecessor,
                        )
                    )
                except Exception as exc:
                    current = await self.load_projection_state(entry.entry_id)
                    if not self._projection_is_reserved(
                        current,
                        event_id=event_id,
                        predecessor_event_id=normalized_predecessor,
                    ):
                        raise ManualEntryProjectionError(
                            "Replacement projection reservation failed"
                        ) from exc
                else:
                    if not reserved:
                        current = await self.load_projection_state(
                            entry.entry_id
                        )
                        if not self._projection_is_reserved(
                            current,
                            event_id=event_id,
                            predecessor_event_id=normalized_predecessor,
                        ):
                            raise ManualEntryProjectionError(
                                "Replacement projection reservation was rejected"
                            )

                entry.pending_l1_event_id = event_id
                entry.pending_l1_predecessor_event_id = normalized_predecessor
                stored_event_id = normalized_event_id(
                    await self._projector.project_current_guarded(
                        entry,
                        predecessor_event_id=normalized_predecessor,
                    )
                )
        except ManualEntryProjectionGovernedError as exc:
            # A pre-existing barrier wins before source reservation. Because
            # reservation and the guarded write share the forget lock, a
            # rejection after reservation can only be an explicit source rule
            # and must end that exact pending source.
            current = await self.load_projection_state(entry.entry_id)
            if self._projection_is_reserved(
                current,
                event_id=event_id,
                predecessor_event_id=normalized_predecessor,
            ):
                self._copy_projection_state(entry, current)
                await self._finalize_governed_projection_rejection(
                    entry,
                    reason=exc.reason,
                )
                raise ManualEntryGovernanceRejectedError(
                    exc.reason,
                ) from exc
            if (
                current.deleted_at is not None
                or current.delete_requested_at is not None
            ):
                raise ManualEntryGovernanceRejectedError(
                    exc.reason,
                ) from exc
            if exc.reason != "time_range":
                await self._finalize_governed_projection_rejection(
                    current,
                    reason=exc.reason,
                )
                raise ManualEntryGovernanceRejectedError(
                    exc.reason,
                ) from exc
            raise ManualEntryGovernanceRejectedError(
                exc.reason,
                source_preserved=True,
            ) from exc
        except ManualEntryWorkflowError:
            raise
        except Exception as exc:
            raise ManualEntryProjectionError(
                "Replacement projection write failed"
            ) from exc

        if stored_event_id is None:
            raise ManualEntryProjectionError(
                "Replacement projection write returned no identity"
            )
        if stored_event_id != event_id:
            await self.forget_event_ids(
                event_ids=[stored_event_id, event_id],
                reason="manual_entry_projection_identity_mismatch",
                block_source_item=False,
            )
            raise ManualEntryProjectionError(
                "Replacement projection write returned a different identity"
            )

        if normalized_predecessor is not None:
            await self.forget_event_ids(
                event_ids=[normalized_predecessor],
                reason=reason,
                block_source_item=False,
            )

        try:
            completed = await self._store.complete_l1_projection(
                entry.entry_id,
                event_id,
                expected_previous_event_id=normalized_predecessor,
            )
        except Exception as exc:
            current = await self.load_projection_state(entry.entry_id)
            if not self._projection_is_complete(current, event_id=event_id):
                if (
                    current.deleted_at is not None
                    or current.delete_requested_at is not None
                ):
                    governance_reason = (
                        await self._current_projection_governance_reason(
                            entry,
                            predecessor_event_id=normalized_predecessor,
                        )
                    )
                    await self._compensate_cancelled_projection(
                        current,
                        event_id,
                    )
                    raise ManualEntryGovernanceRejectedError(
                        governance_reason,
                    ) from exc
                await self._compensate_cancelled_projection(current, event_id)
                raise ManualEntryProjectionError(
                    "Replacement projection link failed"
                ) from exc
            self._copy_projection_state(entry, current)
            return

        if not completed:
            current = await self.load_projection_state(entry.entry_id)
            if not self._projection_is_complete(current, event_id=event_id):
                if (
                    current.deleted_at is not None
                    or current.delete_requested_at is not None
                ):
                    governance_reason = (
                        await self._current_projection_governance_reason(
                            entry,
                            predecessor_event_id=normalized_predecessor,
                        )
                    )
                    await self._compensate_cancelled_projection(
                        current,
                        event_id,
                    )
                    raise ManualEntryGovernanceRejectedError(
                        governance_reason,
                    )
                await self._compensate_cancelled_projection(current, event_id)
                raise ManualEntryProjectionError(
                    "Replacement projection link was rejected"
                )
            self._copy_projection_state(entry, current)
            return

        entry.l1_event_id = event_id
        entry.pending_l1_event_id = None
        entry.pending_l1_predecessor_event_id = None

    @_memory_guarded
    async def repair_projection_if_needed(
        self,
        *,
        entry: ManualEntry,
        reason: str,
    ) -> bool:
        """Finish a projection left incomplete by an earlier request."""
        if entry.delete_requested_at is not None:
            raise ManualEntryDeletionInProgressError("Entry deletion is in progress")

        pending_event_id = normalized_event_id(entry.pending_l1_event_id)
        if pending_event_id is not None:
            if self._projector is None:
                raise ManualEntryProjectionError("Manual-entry projector is unavailable")
            await self.project_and_link(
                entry=entry,
                predecessor_event_id=normalized_event_id(entry.pending_l1_predecessor_event_id),
                replacement_reason=reason,
            )
            return True

        predecessor_event_id = normalized_event_id(entry.l1_event_id)
        if predecessor_event_id is not None:
            if self._memory is None or getattr(self._memory, "l1", None) is None:
                raise ManualEntryCleanupError("Memory L1 store is unavailable")
            try:
                linked = await self._memory.l1.get_event(predecessor_event_id)
            except Exception as exc:
                raise ManualEntryCleanupError("Could not read linked projection") from exc
            if linked is not None:
                if linked.get("deleted_at") is None:
                    return False
                # A present-but-deleted row is durable user governance, not a
                # crash-shaped absence. Advance the source through its own
                # deletion workflow so it cannot be resurrected by recovery.
                await self.delete_entry(entry.entry_id)
                return True

        if self._projector is None:
            raise ManualEntryProjectionError("Manual-entry projector is unavailable")
        await self.project_and_link(
            entry=entry,
            predecessor_event_id=predecessor_event_id,
            replacement_reason=reason,
        )
        return True

    @_memory_guarded
    async def delete_entry(self, entry_id: str) -> ManualEntryDeleteResult:
        """Gate, clean, and finalize one source row idempotently."""
        try:
            existing = await self._store.get(entry_id)
        except Exception as exc:
            raise ManualEntryDeleteStartError("Could not load entry for deletion") from exc
        if existing is None:
            raise ManualEntryNotFoundError("Manual entry does not exist")
        if existing.deleted_at is not None:
            await self.forget_owned_projections(
                entry=existing,
                reason="manual_entry_delete",
                block_source_item=True,
            )
            return ManualEntryDeleteResult(already_deleted=True)

        try:
            delete_requested = await self._store.request_delete(
                entry_id,
                requested_at=self._clock(),
            )
        except Exception as exc:
            current = await self._load_delete_state(entry_id)
            if current.deleted_at is not None:
                return ManualEntryDeleteResult(already_deleted=True)
            if current.delete_requested_at is None:
                raise ManualEntryDeleteStartError("Delete gate did not persist") from exc
            existing = current
        else:
            if not delete_requested:
                current = await self._load_delete_state(entry_id)
                if current.deleted_at is not None:
                    return ManualEntryDeleteResult(already_deleted=True)
                if current.delete_requested_at is None:
                    raise ManualEntryDeleteConflictError("Delete gate was rejected")
                existing = current
            else:
                existing = await self._load_delete_state(entry_id)

        await self.finish_delete(existing)
        return ManualEntryDeleteResult()

    @_memory_guarded
    async def finish_delete(self, entry: ManualEntry) -> None:
        """Resume a previously gated deletion after any process restart."""
        if entry.deleted_at is not None:
            return
        if entry.delete_requested_at is None:
            raise ManualEntryDeleteConflictError("Entry is not delete-gated")

        await self.forget_owned_projections(
            entry=entry,
            reason="manual_entry_delete",
            block_source_item=True,
        )

        try:
            finalized = await self._store.finalize_delete(
                entry.entry_id,
                deleted_at=self._clock(),
            )
        except Exception as exc:
            current = await self._load_delete_state(entry.entry_id)
            if current.deleted_at is None:
                raise ManualEntryDeleteCompletionError(
                    "Delete finalization did not persist"
                ) from exc
            return
        if not finalized:
            current = await self._load_delete_state(entry.entry_id)
            if current.deleted_at is None:
                raise ManualEntryDeleteConflictError("Delete finalization was rejected")

    @_memory_guarded
    async def recover_entry(self, entry: ManualEntry) -> bool:
        """Advance one row selected by the durable recovery scan."""
        if entry.delete_requested_at is not None:
            await self.finish_delete(entry)
            return True
        try:
            return await self.repair_projection_if_needed(
                entry=entry,
                reason="manual_entry_recovery",
            )
        except ManualEntryGovernanceRejectedError:
            current = await self.load_projection_state(entry.entry_id)
            if current.deleted_at is not None:
                self._copy_projection_state(entry, current)
                return True
            raise

    async def _finalize_governed_projection_rejection(
        self,
        entry: ManualEntry,
        *,
        reason: str,
    ) -> None:
        """End the exact source state that a durable forget rule rejected."""
        try:
            await self.delete_entry(entry.entry_id)
        except Exception as exc:
            # Once governance has rejected an occurrence, the API must never
            # downgrade it to a normal delayed projection. Delete gating and
            # recovery may still be pending, but the user-visible outcome is
            # terminal.
            raise ManualEntryGovernanceRejectedError(reason) from exc
        try:
            current = await self.load_projection_state(entry.entry_id)
        except ManualEntryWorkflowError as exc:
            raise ManualEntryGovernanceRejectedError(reason) from exc
        if current.deleted_at is None:
            raise ManualEntryGovernanceRejectedError(reason)
        self._copy_projection_state(entry, current)

    async def _current_projection_governance_reason(
        self,
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str:
        """Reload the durable rule that terminalized a pending replacement."""
        try:
            await self._projector.ensure_projectable(
                entry,
                predecessor_event_id=predecessor_event_id,
            )
        except ManualEntryProjectionGovernedError as exc:
            return exc.reason
        except Exception:
            # The caller only asks after the source is already delete-gated
            # or deleted. A transient reason lookup must not turn a terminal
            # outcome into a retryable projection failure.
            return "source_reference"
        return "source_reference"

    def _memory_operation_guard(self) -> Any:
        factory = getattr(self._memory, "memory_operation_guard", None)
        if not callable(factory):
            raise ManualEntryWorkflowError("Memory operation guard is unavailable")
        return factory()

    async def _load_delete_state(self, entry_id: str) -> ManualEntry:
        try:
            current = await self._store.get(entry_id)
        except Exception as exc:
            raise ManualEntryDeleteCompletionError("Could not reload delete state") from exc
        if current is None:
            raise ManualEntryDeleteCompletionError("Delete source row is missing")
        return current

    async def _compensate_cancelled_projection(
        self,
        current: ManualEntry,
        event_id: str,
    ) -> None:
        if current.delete_requested_at is None and current.deleted_at is None:
            return
        await self.forget_event_ids(
            event_ids=[event_id],
            reason="manual_entry_projection_cancelled",
            block_source_item=False,
        )

    @staticmethod
    def _projection_is_reserved(
        entry: ManualEntry | None,
        *,
        event_id: str,
        predecessor_event_id: str | None,
    ) -> bool:
        return bool(
            entry is not None
            and entry.deleted_at is None
            and entry.delete_requested_at is None
            and normalized_event_id(entry.l1_event_id) == predecessor_event_id
            and normalized_event_id(entry.pending_l1_event_id) == event_id
            and normalized_event_id(entry.pending_l1_predecessor_event_id) == predecessor_event_id
        )

    @staticmethod
    def _projection_is_complete(
        entry: ManualEntry | None,
        *,
        event_id: str,
    ) -> bool:
        return bool(
            entry is not None
            and entry.deleted_at is None
            and entry.delete_requested_at is None
            and normalized_event_id(entry.l1_event_id) == event_id
            and normalized_event_id(entry.pending_l1_event_id) is None
            and normalized_event_id(entry.pending_l1_predecessor_event_id) is None
        )

    @staticmethod
    def _copy_projection_state(target: ManualEntry, source: ManualEntry) -> None:
        target.l1_event_id = source.l1_event_id
        target.pending_l1_event_id = source.pending_l1_event_id
        target.pending_l1_predecessor_event_id = source.pending_l1_predecessor_event_id
        target.delete_requested_at = source.delete_requested_at
        target.deleted_at = source.deleted_at


__all__ = [
    "ManualEntryCleanupError",
    "ManualEntryDeleteCompletionError",
    "ManualEntryDeleteConflictError",
    "ManualEntryDeleteResult",
    "ManualEntryDeleteStartError",
    "ManualEntryDeletionInProgressError",
    "ManualEntryGovernanceRejectedError",
    "ManualEntryNotFoundError",
    "ManualEntryProjectionError",
    "ManualEntryWorkflow",
    "ManualEntryWorkflowError",
    "normalized_event_id",
    "projection_recovery_required",
]
