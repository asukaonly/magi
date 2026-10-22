"""Narrow persistence contracts for dependencies and private artifact ownership."""

from dataclasses import dataclass
from typing import Protocol

from ..core.code_agent_artifacts import CodeAgentDelegationReference


class ChatConsumedEventsRepository(Protocol):
    async def record_consumed(self, *, session_id: str, run_id: str, revision: int, message_ids: list[str]) -> None: ...
    async def find_runs_that_consumed(self, *, session_id: str, message_id: str) -> list[tuple[str, int]]: ...
    async def clear_for_run(self, *, session_id: str, run_id: str) -> None: ...


class ChatArtifactRepository(Protocol):
    async def register_code_artifact(self, reference: CodeAgentDelegationReference, *, created_at_ms: int) -> None: ...


@dataclass(frozen=True)
class ChatAssetOwnership:
    active_session_ids: tuple[str, ...]
    owned_asset_keys: tuple[str, ...]


class ChatAssetOwnershipRepository(Protocol):
    def get_active_asset_ownership(self) -> ChatAssetOwnership | None: ...
