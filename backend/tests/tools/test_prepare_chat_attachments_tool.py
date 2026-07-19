from __future__ import annotations

from pathlib import Path

import pytest

from magi.tools.builtin.prepare_chat_attachments_tool import (
    PrepareChatAttachmentsTool,
)
from magi.tools.schema import ToolExecutionContext
from magi_plugin_sdk.capabilities import ToolCapabilities


class _AsyncChatPort:
    def __init__(self) -> None:
        self.imported_paths: list[str] = []

    def get_attachment_payload(self, user_id, session_id, attachment_id):
        return None

    async def prepare_runtime_attachment(
        self,
        *,
        session_id,
        turn_id,
        attachment,
    ):
        return attachment

    async def ingest_local_file(
        self,
        *,
        session_id,
        turn_id,
        file_path,
        original_name=None,
        mime_type=None,
    ):
        assert session_id == "session-1"
        assert turn_id == "turn-1"
        assert Path(file_path).is_file()
        self.imported_paths.append(file_path)
        return {
            "attachment_id": "attachment-1",
            "kind": "text_file",
            "original_name": Path(file_path).name,
        }


@pytest.mark.asyncio
async def test_prepare_chat_attachments_awaits_chat_port_import(
    tmp_path: Path,
) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello", encoding="utf-8")
    chat_port = _AsyncChatPort()
    context = ToolExecutionContext(
        agent_id="chat-agent",
        env_vars={"session_id": "session-1", "turn_id": "turn-1"},
        capabilities=ToolCapabilities(chat=chat_port),
    )

    result = await PrepareChatAttachmentsTool().execute(
        {"file_paths": [str(source)]},
        context,
    )

    assert result.success is True
    assert chat_port.imported_paths == [str(source)]
    assert result.data["chat_attachments"] == [
        {
            "attachment_id": "attachment-1",
            "kind": "text_file",
            "original_name": "notes.txt",
        }
    ]
