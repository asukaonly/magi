from __future__ import annotations

from fastapi.testclient import TestClient

from magi.transport.http_app import create_transport_app


def test_builtin_avatar_is_served_from_static_path() -> None:
    client = TestClient(create_transport_app())

    response = client.get("/static/avatars/seven.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_personality_list_returns_static_avatar_paths() -> None:
    client = TestClient(create_transport_app())

    response = client.get(
        "/api/personalities/",
        params={"lang": "zh"},
    )

    assert response.status_code == 200
    payload = response.json()
    seven = next(item for item in payload["data"] if item["id"] == "seven_hacker")
    assert seven["avatar"] == "/static/avatars/seven.png"
