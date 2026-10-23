"""Attachment authorization stays with the chat owner, independent of file transport."""
from _shared.chat_stores import build_chat_reader
from contextlib import closing
import sqlite3
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from magi.chat.storage.schema import CHAT_STORE_SCHEMA_SQL
from magi.ipc import attachment_handler
from magi.ipc.protocol import IpcRequest
from magi.ipc.server import _is_read


@pytest.fixture
def attachment_owner(tmp_path):
    path = tmp_path / "chat.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(CHAT_STORE_SCHEMA_SQL)
        conn.execute("INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES('session','local_user','Title',1,1)")
        conn.execute("INSERT INTO chat_messages(message_id,session_id,turn_id,user_id,role,message_kind,created_at_ms,sequence_no) VALUES('message','session','turn','local_user','user','text',1,1)")
        conn.execute("INSERT INTO chat_attachments(attachment_id,session_id,turn_id,message_id,user_id,kind,storage_rel_path,created_at_ms) VALUES('attachment','session','turn','message','local_user','text_file','data/resources/chat/files/session/turn/attachment__test.txt',1)")
        conn.commit()
    service = build_chat_reader()
    service.repository.database.path = path
    return service, path


@pytest.mark.asyncio
async def test_private_lookup_returns_owned_metadata_without_opening_file(attachment_owner, monkeypatch):
    service, _ = attachment_owner
    monkeypatch.setattr(attachment_handler, "require_chat_read_service", lambda: service)
    params = {"user_id": "local_user", "session_id": "session", "attachment_id": "attachment"}
    response = await attachment_handler.resolve_chat_attachment(params)
    assert response["attachment"]["turn_id"] == "turn"
    assert response["attachment"]["storage_rel_path"].endswith("attachment__test.txt")
    assert "storage_path" not in response["attachment"]
    assert _is_read(IpcRequest(id="lookup", method="chat.resolve_attachment", params=params))


@pytest.mark.parametrize("mutation", [
    "UPDATE chat_messages SET is_visible=0",
    "UPDATE chat_sessions SET deleted_at_ms=2",
    "UPDATE chat_messages SET turn_id='other'",
    "UPDATE chat_messages SET user_id='other'",
    "UPDATE chat_messages SET session_id='other'",
    "UPDATE chat_attachments SET storage_rel_path=''",
])
def test_exact_visible_owner_required(attachment_owner, mutation):
    service, path = attachment_owner
    assert service.get_attachment_location("local_user", "session", "attachment") is not None
    assert service.get_attachment_location("other", "session", "attachment") is None
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(mutation)
        conn.commit()
    assert service.get_attachment_location("local_user", "session", "attachment") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [None, {}, {"user_id": 2, "session_id": "s", "attachment_id": "a"}, {"user_id": "u", "session_id": "s", "attachment_id": "a", "storage_path": "/private"}])
async def test_lookup_rejects_untrusted_shape_before_owner_access(monkeypatch, params):
    owner = AsyncMock()
    monkeypatch.setattr(attachment_handler, "require_chat_read_service", lambda: owner)
    with pytest.raises(ValidationError):
        await attachment_handler.resolve_chat_attachment(params)
    owner.aget_attachment_location.assert_not_called()
