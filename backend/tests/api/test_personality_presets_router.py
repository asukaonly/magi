from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from magi.api import avatar_paths
from magi.transport.http_app import create_transport_app


@pytest.mark.parametrize(
    "name", ["echo", "seven", "sichen", "sumen", "nova", "jinx", "halberd", "ember"]
)
def test_builtin_avatar_is_served_from_static_path(name: str) -> None:
    client = TestClient(create_transport_app())

    response = client.get(f"/static/avatars/{name}.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_builtin_avatar_dir_prefers_pyinstaller_internal_layout(tmp_path, monkeypatch) -> None:
    internal_avatar_dir = tmp_path / "sidecar-dist" / "_internal" / "personalities" / "avatar"
    source_avatar_dir = tmp_path / "sidecar-dist" / "personalities" / "avatar"
    module_file = tmp_path / "sidecar-dist" / "_internal" / "magi" / "api" / "avatar_paths.py"
    internal_avatar_dir.mkdir(parents=True)
    source_avatar_dir.mkdir(parents=True)
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(avatar_paths, "__file__", str(module_file))

    assert avatar_paths.builtin_avatar_dir() == internal_avatar_dir


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("zh", {
            "echo_ai_assistant": "/static/avatars/echo.svg",
            "seven_hacker": "/static/avatars/seven.svg",
            "sichen": "/static/avatars/sichen.svg",
            "sumen_listener": "/static/avatars/sumen.svg",
        }),
        ("en", {
            "nova_assistant": "/static/avatars/nova.svg",
            "jinx_hacker": "/static/avatars/jinx.svg",
            "halberd": "/static/avatars/halberd.svg",
            "ember": "/static/avatars/ember.svg",
        }),
    ],
)
def test_personality_list_returns_static_avatar_paths(
    locale: str, expected: dict[str, str]
) -> None:
    client = TestClient(create_transport_app())

    response = client.get(
        "/api/personalities/",
        params={"lang": locale},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "OK"
    assert {item["id"]: item["avatar"] for item in payload["data"]} == expected


def test_personality_preset_detail_returns_localized_not_found() -> None:
    client = TestClient(create_transport_app())

    response = client.get(
        "/api/personalities/missing_preset",
        params={"lang": "zh"},
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到人格预设：missing_preset"


def test_personality_avatar_upload_returns_localized_format_error() -> None:
    client = TestClient(create_transport_app())

    response = client.post(
        "/api/personalities/avatar/upload",
        files={"file": ("avatar.gif", b"not-an-image", "image/gif")},
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "不支持的图片格式"
