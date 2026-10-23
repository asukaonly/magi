"""Committed cleanup work shared by the application and persistence ports."""

from dataclasses import dataclass, field
from typing import Protocol, Literal
from ..core.code_agent_artifacts import (
    CodeAgentDelegationReference,
    WorkspaceSessionArtifactReference,
)


@dataclass(slots=True)
class ChatCleanupPlan:
    kind: Literal["message", "history", "session", "global"]
    user_id: str = ""
    session_id: str = ""
    message_ids: list[str] = field(default_factory=list)
    turn_ids: list[str] = field(default_factory=list)
    trace_turn_ids: list[str] = field(default_factory=list)
    whole_session: bool = False
    asset_references: list[tuple[str, str]] = field(default_factory=list)
    code_references: list[CodeAgentDelegationReference] = field(default_factory=list)
    workspace_references: list[WorkspaceSessionArtifactReference] = field(default_factory=list)
    removed_count: int = 0


class ChatAssetInventory(Protocol):
    def list_snapshot_asset_references(
        self, *, session_id: str, turn_ids: list[str], delete_entire_session: bool
    ) -> list[tuple[str, str]]: ...


class ChatCleanupTransactions(Protocol):
    def prepare_message_cleanup(
        self, user_id: str, session_id: str, message_id: str
    ) -> ChatCleanupPlan | None: ...
    def prepare_history_cleanup(
        self, user_id: str, session_id: str, message_ids: list[str], turn_ids: list[str]
    ) -> ChatCleanupPlan | None: ...
    def prepare_session_cleanup(self, user_id: str, session_id: str) -> ChatCleanupPlan | None: ...
    def prepare_global_cleanup(self) -> ChatCleanupPlan: ...
    def finish_message_cleanup(self, plan: ChatCleanupPlan) -> None: ...
    def finish_history_cleanup(self, plan: ChatCleanupPlan) -> None: ...
    def finish_session_cleanup(self, plan: ChatCleanupPlan) -> None: ...
    def finish_global_cleanup(self, plan: ChatCleanupPlan) -> None: ...
    def history_cleanup_scope(
        self, user_id: str, session_id: str
    ) -> tuple[list[str], list[str]]: ...
