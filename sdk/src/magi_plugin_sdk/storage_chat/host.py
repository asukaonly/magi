"""Explicit host effects used by relational chat workflows."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from ..storage_models.chat import ChatMessageRecord


class PreparedChatAssets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachments: list[dict[str, JsonValue]]
    references: list[tuple[str, str, str]]


class ChatStorageHost(Protocol):
    def prepare_assets(
        self, message: ChatMessageRecord, payloads: list[dict[str, object]],
    ) -> PreparedChatAssets: ...

    def claim_workspace_identity(self, path: str | None) -> None: ...

    def list_snapshot_asset_references(
        self, *, session_id: str, turn_ids: list[str], delete_entire_session: bool,
    ) -> list[tuple[str, str]]: ...

    def get_read_revision(self, *, user_id: str, session_id: str) -> str: ...

    def get_trace_summary(
        self, *, user_id: str, session_id: str, turn_id: str,
    ) -> dict[str, Any] | None: ...

    def get_turn_activity_map(self, *, user_id: str, session_id: str) -> dict[str, Any]: ...
