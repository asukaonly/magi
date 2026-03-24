from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from magi.utils.runtime import get_runtime_paths, set_runtime_dir
from magi.websocket.http_app import create_transport_app


def test_upload_chat_attachment_returns_normalized_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "magi.websocket.http_middleware.get_required_desktop_session_token",
        lambda: "desktop-secret",
    )

    original_runtime_base = get_runtime_paths().base_dir
    runtime_dir = tmp_path / "runtime"
    set_runtime_dir(runtime_dir)

    try:
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
            headers={"X-Magi-Session-Token": "desktop-secret"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        attachment = payload["data"]["attachment"]
        assert attachment["kind"] == "text_file"
        assert attachment["original_name"] == "notes.md"
        assert attachment["parse_status"] == "parsed"
        assert Path(attachment["storage_path"]).is_file()
        assert Path(attachment["derived_text_path"]).is_file()
    finally:
        set_runtime_dir(original_runtime_base)
