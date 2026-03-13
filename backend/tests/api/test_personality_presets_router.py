from __future__ import annotations

from fastapi.testclient import TestClient

from magi.api.app import create_app


def test_builtin_avatar_is_served_from_static_path(monkeypatch) -> None:
    monkeypatch.setenv("MAGI_DESKTOP_SESSION_TOKEN", "desktop-secret")

    client = TestClient(create_app())

    response = client.get("/static/avatars/system-melchior.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_personality_list_returns_static_avatar_paths(monkeypatch) -> None:
    monkeypatch.setenv("MAGI_DESKTOP_SESSION_TOKEN", "desktop-secret")

    client = TestClient(create_app())

    response = client.get(
        "/api/personalities/",
        params={"lang": "zh"},
        headers={"X-Magi-Session-Token": "desktop-secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    melchior = next(item for item in payload["data"] if item["id"] == "melchior")
    assert melchior["avatar"] == "/static/avatars/system-melchior.jpg"
