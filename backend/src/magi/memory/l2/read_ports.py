"""Storage-independent, governance-aware reads for memory presentation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from ..context_scope.models import ContextOption
from .corrections.models import CorrectionTargetKind, MemoryCorrection


class MemoryContextRepository(Protocol):
    async def sync_workspace_project_options(
        self, workspace_paths: list[str]
    ) -> list[ContextOption]: ...
    async def validate_correction_scope(
        self, scope: dict[str, Any] | None
    ) -> dict[str, list[dict[str, str]]]: ...
    async def get_context_labels(self, context_ids: set[str]) -> dict[str, str]: ...


class MemoryPresentationRepository(Protocol):
    """Return public values after applying authoritative forgetting policies."""

    async def get_canonical_names(self, entity_ids: Iterable[str]) -> dict[str, str]: ...
    async def decorate_assertions(
        self, assertions: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]: ...
    async def get_correction(self, correction_id: str) -> MemoryCorrection | None: ...
    async def get_correction_by_request_id(self, request_id: str) -> MemoryCorrection | None: ...
    async def correction_history_slot_key(
        self, *, target_kind: CorrectionTargetKind, target_id: str
    ) -> str | None: ...
    async def prepare_correction_history(
        self,
        *,
        target_kind: CorrectionTargetKind,
        versions: Sequence[Mapping[str, Any]],
        corrections: Sequence[object],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...
    async def decorate_correction_records(
        self, corrections: Sequence[object]
    ) -> list[dict[str, Any]]: ...
    async def public_current_claim(
        self, target_kind: CorrectionTargetKind, value: Mapping[str, Any] | None
    ) -> dict[str, Any] | None: ...
