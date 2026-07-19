from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
from magi.core.container import get_container
from magi.utils.runtime import get_runtime_paths, set_runtime_dir
from magi.transport.http_app import create_transport_app


def test_upload_chat_attachment_returns_normalized_metadata(monkeypatch, tmp_path: Path) -> None:
    original_runtime_base = get_runtime_paths().base_dir
    runtime_dir = tmp_path / "runtime"
    set_runtime_dir(runtime_dir)

    try:
        class _ReadService:
            async def aget_session_summary(
                self,
                _user_id: str,
                _session_id: str,
            ) -> object:
                return object()

        ingestion_service = LocalChatAttachmentIngestionService(
            runtime_paths=get_runtime_paths(),
            chat_read_service_factory=lambda: _ReadService(),
        )
        with get_container().chat_attachment_ingestion_service.override(
            ingestion_service
        ):
            client = TestClient(create_transport_app())
            response = client.post(
                "/api/messages/session/session-1/attachments",
                data={
                    "user_id": "local_user",
                    "turn_id": "turn-1",
                },
                files={
                    "file": ("notes.md", b"# hello\nworld\n", "text/markdown"),
                },
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        attachment = payload["data"]["attachment"]
        assert attachment["kind"] == "text_file"
        assert attachment["original_name"] == "notes.md"
        assert attachment["parse_status"] == "pending"
        assert Path(attachment["storage_path"]).is_file()
        assert "derived_text_path" not in attachment
    finally:
        set_runtime_dir(original_runtime_base)
