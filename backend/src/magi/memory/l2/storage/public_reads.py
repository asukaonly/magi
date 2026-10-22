"""SQLite adapter for governed memory presentation reads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..assertion_display import decorate_assertion_display
from ..corrections import history
from ..corrections.models import CorrectionTargetKind, MemoryCorrection
from ..corrections.repository import MemoryCorrectionRepository
from ..entities.catalog.lookup import get_canonical_names


class SqliteMemoryPresentationRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._corrections = MemoryCorrectionRepository(db_path)

    async def get_canonical_names(self, entity_ids: Iterable[str]) -> dict[str, str]:
        return await get_canonical_names(self._db_path, entity_ids)

    async def decorate_assertions(
        self, assertions: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        return await decorate_assertion_display(self._db_path, assertions)

    async def get_correction(self, correction_id: str) -> MemoryCorrection | None:
        return await self._corrections.get(correction_id)

    async def get_correction_by_request_id(self, request_id: str) -> MemoryCorrection | None:
        return await self._corrections.get_by_request_id(request_id)

    async def correction_history_slot_key(
        self, *, target_kind: CorrectionTargetKind, target_id: str
    ) -> str | None:
        return await history.correction_history_slot_key(
            self._db_path, target_kind=target_kind, target_id=target_id
        )

    async def prepare_correction_history(
        self,
        *,
        target_kind: CorrectionTargetKind,
        versions: Sequence[Mapping[str, Any]],
        corrections: Sequence[object],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return await history.prepare_correction_history(
            self._db_path, target_kind=target_kind, versions=versions, corrections=corrections
        )

    async def decorate_correction_records(
        self, corrections: Sequence[object]
    ) -> list[dict[str, Any]]:
        return await history.decorate_correction_records(self._db_path, corrections)

    async def public_current_claim(
        self, target_kind: CorrectionTargetKind, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None:
        return await history.public_current_claim(self._db_path, target_kind, value)
