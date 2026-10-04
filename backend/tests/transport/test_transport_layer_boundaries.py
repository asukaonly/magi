from __future__ import annotations

from pathlib import Path


def test_api_route_registration_does_not_import_transport() -> None:
    from magi.api import routes as api_routes

    source = Path(api_routes.__file__).read_text(encoding="utf-8")

    assert "register_websocket" not in source
    assert "FastAPI(" not in source
