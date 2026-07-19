from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from magi.core.chat_assets.mutations import run_chat_asset_mutation
from magi.tools.builtin.read_chat_attachment_tool import ReadChatAttachmentTool
from magi.tools.schema import ToolExecutionContext
from magi.utils.runtime import get_runtime_paths, set_runtime_dir
from magi_plugin_sdk.capabilities import ToolCapabilities


class _FakeChatPort:
    """Fake ChatPort that routes through the real ingestion service for parse calls."""

    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        # Use the real ingestion service for prepare_runtime_attachment so that
        # file parsing (text extraction, derived path writing) works in tests.
        from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
        self._ingestion = LocalChatAttachmentIngestionService()

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        assert user_id == "local_user"
        assert session_id == "session-1"
        assert attachment_id == "att-1"
        return self.payload

    async def prepare_runtime_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]:
        return await run_chat_asset_mutation(
            self._ingestion.prepare_runtime_attachment,
            session_id=session_id,
            turn_id=turn_id,
            attachment=attachment,
        )

    async def ingest_local_file(self, *, session_id, turn_id, file_path, original_name=None, mime_type=None):
        return {}


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="chat-agent",
        env_vars={"user_id": "local_user", "session_id": "session-1", "turn_id": "turn-current"},
        capabilities=ToolCapabilities(chat=_FakeChatPort(None)),  # placeholder; overridden per-test
    )


@pytest.mark.asyncio
async def test_read_chat_attachment_reads_text_attachment_by_id(tmp_path: Path) -> None:
    original_runtime_base = get_runtime_paths().base_dir
    set_runtime_dir(tmp_path / "runtime")
    try:
        runtime_paths = get_runtime_paths()
        attachment_dir = runtime_paths.chat_files_dir / "session-1" / "turn-1"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        attachment_path = attachment_dir / "att-1__notes.md"
        attachment_path.write_text("Alpha\nBeta\nGamma", encoding="utf-8")
        payload = {
            "attachment_id": "att-1",
            "turn_id": "turn-1",
            "kind": "text_file",
            "original_name": "notes.md",
            "mime_type": "text/markdown",
            "size_bytes": attachment_path.stat().st_size,
            "storage_path": str(attachment_path),
            "sha256": "sha",
        }
        caps = ToolCapabilities(chat=_FakeChatPort(payload))
        ctx = ToolExecutionContext(
            agent_id="chat-agent",
            env_vars={"user_id": "local_user", "session_id": "session-1", "turn_id": "turn-current"},
            capabilities=caps,
        )
        tool = ReadChatAttachmentTool()

        result = await tool.execute({"attachment_id": "att-1", "limit": 8}, ctx)

        assert result.success is True
        assert result.data["text"] == "Alpha\nBe"
        assert result.data["is_complete"] is False
        assert result.data["next_offset"] == 8
        assert result.data["attachment"]["attachment_id"] == "att-1"
        assert result.data["attachment"]["turn_id"] == "turn-1"
        assert "storage_path" not in result.data["attachment"]
        assert (runtime_paths.chat_derived_dir / "session-1" / "turn-1" / "att-1.txt").is_file()
    finally:
        set_runtime_dir(original_runtime_base)


@pytest.mark.asyncio
async def test_read_chat_attachment_returns_image_metadata_without_path(tmp_path: Path) -> None:
    original_runtime_base = get_runtime_paths().base_dir
    set_runtime_dir(tmp_path / "runtime")
    try:
        runtime_paths = get_runtime_paths()
        attachment_dir = runtime_paths.chat_images_dir / "session-1" / "turn-1"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        attachment_path = attachment_dir / "att-1__photo.png"
        attachment_path.write_bytes(b"png")
        payload = {
            "attachment_id": "att-1",
            "turn_id": "turn-1",
            "kind": "image",
            "original_name": "photo.png",
            "mime_type": "image/png",
            "size_bytes": attachment_path.stat().st_size,
            "storage_path": str(attachment_path),
        }
        caps = ToolCapabilities(chat=_FakeChatPort(payload))
        ctx = ToolExecutionContext(
            agent_id="chat-agent",
            env_vars={"user_id": "local_user", "session_id": "session-1", "turn_id": "turn-current"},
            capabilities=caps,
        )
        tool = ReadChatAttachmentTool()

        result = await tool.execute({"attachment_id": "att-1"}, ctx)

        assert result.success is True
        assert result.data["content_kind"] == "image"
        assert result.data["readable_text"] is False
        assert result.data["attachment"]["original_name"] == "photo.png"
        assert "storage_path" not in result.data["attachment"]
    finally:
        set_runtime_dir(original_runtime_base)


@pytest.mark.asyncio
async def test_read_chat_attachment_requires_session_id() -> None:
    caps = ToolCapabilities(chat=_FakeChatPort(None))
    tool = ReadChatAttachmentTool()

    result = await tool.execute(
        {"attachment_id": "att-1"},
        ToolExecutionContext(
            agent_id="chat-agent",
            env_vars={"user_id": "local_user"},
            capabilities=caps,
        ),
    )

    assert result.success is False
    assert "session_id is required" in str(result.error)
