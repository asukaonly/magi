"""Host-owned files and trace reads used by storage implementations."""

from collections.abc import Callable
from typing import Any
from magi_plugin_sdk.storage_chat.host import PreparedChatAssets
from ...core.chat_assets.mutations import require_chat_asset_mutation
from ...utils.runtime import RuntimePaths
from ..asset_gc import ChatAssetGC
from ..asset_validation import validate_message_asset_payloads
from ..contracts import ChatMessageRecord
from ..workspace_identity import claim_workspace_identity
from .serialization import message_asset_references, message_attachment_storage_reference


class LocalChatStorageHost:
    def __init__(self, paths: RuntimePaths, *, assets: Any = None, trace: Callable[[], Any] | None = None) -> None:
        self.paths = paths
        self.assets = assets or ChatAssetGC(runtime_paths=paths)
        self._trace = trace

    def prepare_assets(self, message: ChatMessageRecord, payloads: list[dict[str, object]]) -> PreparedChatAssets:
        require_chat_asset_mutation()
        validate_message_asset_payloads(payloads, session_id=message.session_id, turn_id=message.turn_id, runtime_paths=self.paths)
        managed = [item for item in payloads if str(item.get("kind") or "").strip() != "mcp_resource"]
        attachments = []
        for item in managed:
            reference = message_attachment_storage_reference(
                item.get("storage_path"), session_id=message.session_id, turn_id=message.turn_id,
                attachment_id=str(item.get("attachment_id") or ""), runtime_paths=self.paths,
            )
            if reference is not None:
                attachments.append({**item, "storage_rel_path": reference[1]})
        return PreparedChatAssets(attachments=attachments, references=message_asset_references(
            managed, session_id=message.session_id, turn_id=message.turn_id, runtime_paths=self.paths,
        ))

    def claim_workspace_identity(self, path: str | None) -> None:
        claim_workspace_identity(path)

    def list_snapshot_asset_references(self, *, session_id: str, turn_ids: list[str], delete_entire_session: bool) -> list[tuple[str, str]]:
        return self.assets.list_snapshot_asset_references(session_id=session_id, turn_ids=turn_ids, delete_entire_session=delete_entire_session)

    def _trace_service(self) -> Any:
        if self._trace is not None:
            return self._trace()
        from ...runtime_trace.chat_trace.read_service import get_chat_trace_read_service
        return get_chat_trace_read_service()

    def get_read_revision(self, *, user_id: str, session_id: str) -> str:
        return self._trace_service().get_read_revision(user_id=user_id, session_id=session_id)

    def get_trace_summary(self, *, user_id: str, session_id: str, turn_id: str) -> dict[str, Any] | None:
        return self._trace_service().get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)

    def get_turn_activity_map(self, *, user_id: str, session_id: str) -> dict[str, Any]:
        return self._trace_service().get_turn_activity_map(user_id=user_id, session_id=session_id)
