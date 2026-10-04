from __future__ import annotations

from pathlib import Path


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source


def test_personality_config_router_does_not_read_builtin_preset_files() -> None:
    from magi.api.routers import personality_config as personality_config_router

    source = Path(personality_config_router.__file__).read_text(encoding="utf-8")

    assert "_get_builtin_personalities_dir" not in source
    assert "_load_builtin_personality" not in source
    assert "backend/personalities" not in source
    assert ".glob(\"*.json\")" not in source
