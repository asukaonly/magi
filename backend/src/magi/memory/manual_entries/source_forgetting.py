"""Finalize manual-entry sources selected by durable memory forgetting."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..forgetting import (
    SourceForgetBatch,
    SourceForgetClaim,
    SourceForgetGateResult,
)
from .workflow import normalized_event_id


class ManualEntrySourceForgetOwner:
    """Gate a source at selection and finalize it after exact cleanup."""

    def __init__(
        self,
        *,
        store: Any,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._clock = clock

    async def gate(
        self,
        batch: SourceForgetBatch,
    ) -> SourceForgetGateResult:
        """Close mutation and claim every current projection for exact cleanup."""
        selected_by_entry: dict[str, set[str]] = {}
        for identity in batch.identities:
            selected_by_entry.setdefault(identity.source_item_id, set()).add(
                identity.event_id
            )

        gate = await self._store.gate_source_forget_entries(
            {
                entry_id: tuple(sorted(event_ids))
                for entry_id, event_ids in selected_by_entry.items()
            },
            requested_at=self._clock(),
        )
        claims: list[SourceForgetClaim] = []
        for current in gate.gated_entries:
            if current.delete_requested_at is None:
                raise RuntimeError("Manual-entry source gate was rejected")
            owned_event_ids = set(selected_by_entry[current.entry_id])
            for event_id in (
                normalized_event_id(current.l1_event_id),
                normalized_event_id(current.pending_l1_event_id),
            ):
                if event_id is not None:
                    owned_event_ids.add(event_id)
            claims.append(
                SourceForgetClaim(
                    source="manual_entry",
                    source_item_id=current.entry_id,
                    event_ids=tuple(sorted(owned_event_ids)),
                )
            )
        return SourceForgetGateResult(
            claims=tuple(claims),
            exact_only_event_ids=gate.obsolete_event_ids,
        )

    async def finalize(
        self,
        claims: tuple[SourceForgetClaim, ...],
    ) -> None:
        """Finalize gated sources in bounded batches after memory cleanup."""
        for offset in range(0, len(claims), 1000):
            chunk = claims[offset : offset + 1000]
            await self._store.finalize_source_forget_entries(
                {
                    claim.source_item_id: claim.event_ids
                    for claim in chunk
                },
                deleted_at=self._clock(),
            )


__all__ = ["ManualEntrySourceForgetOwner"]
