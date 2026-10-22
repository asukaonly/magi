"""Persistence contracts consumed by derived artifact owners."""

from collections.abc import Iterable
from typing import Protocol


class DerivationDependencyRepository(Protocol):
    async def replace_dependencies(
        self,
        *,
        artifact_kind: str,
        artifact_id: str,
        subject_key: str,
        source_revision: int,
        sources: Iterable[tuple[str, str]],
    ) -> None: ...
