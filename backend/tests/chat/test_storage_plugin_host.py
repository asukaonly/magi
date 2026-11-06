"""Storage workers cannot expand the scope of host-side chat effects."""

from unittest.mock import Mock
import pytest
from magi_plugin_sdk.storage import StorageCall
from magi.chat.storage.plugin_proxy import ScopedChatHost


def request(operation="get_history_page", repository="reads", **arguments):
    return StorageCall(session_id="storage", repository=repository, operation=operation, arguments=arguments)


def test_trace_callback_is_scoped_to_original_user_and_session():
    host = Mock()
    host.get_read_revision.return_value = "rev-1"
    callback = ScopedChatHost(host, request(user_id="owner", session_id="chat"))
    assert callback("get_read_revision", {"user_id": "owner", "session_id": "chat"})["value"] == "rev-1"
    with pytest.raises(PermissionError):
        callback("get_read_revision", {"user_id": "other", "session_id": "chat"})
    with pytest.raises(PermissionError):
        callback("get_read_revision", {"user_id": "owner", "session_id": "other"})
    with pytest.raises(PermissionError):
        callback("claim_workspace_identity", {"path": "/private"})
    assert host.get_read_revision.call_count == 1


def test_storage_worker_cannot_replace_attachment_payloads_or_scope():
    callback = ScopedChatHost(Mock(), request("append_message", "chat", record={
        "user_id": "owner", "session_id": "chat", "turn_id": "turn",
    }, attachment_payloads=[{"storage_path": "original"}]))
    values = {"message": {"user_id": "owner", "session_id": "chat", "turn_id": "turn"},
              "payloads": [{"storage_path": "different"}]}
    with pytest.raises(PermissionError):
        callback("prepare_assets", values)
    values["payloads"] = [{"storage_path": "original"}]
    values["message"]["session_id"] = "other"
    with pytest.raises(PermissionError):
        callback("prepare_assets", values)


def test_inventory_and_workspace_callbacks_require_exact_request_scope():
    host = Mock()
    host.list_snapshot_asset_references.return_value = [("key", "resources/chat/chat/turn/a")]
    callback = ScopedChatHost(host, request("prepare_history_cleanup", session_id="chat"))
    assert callback("list_snapshot_asset_references", {
        "session_id": "chat", "turn_ids": ["turn"], "delete_entire_session": False,
    })["value"] == [["key", "resources/chat/chat/turn/a"]]
    with pytest.raises(PermissionError):
        callback("list_snapshot_asset_references", {"session_id": "other", "turn_ids": [], "delete_entire_session": True})
    callback = ScopedChatHost(host, request("update_session_workspace", workspace_path="/selected"))
    with pytest.raises(PermissionError):
        callback("claim_workspace_identity", {"path": "/other"})
