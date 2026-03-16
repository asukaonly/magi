from __future__ import annotations

from pathlib import Path


def test_messages_router_does_not_define_global_user_message_sensor() -> None:
    from magi.api.routers import messages as messages_router

    source = Path(messages_router.__file__).read_text(encoding="utf-8")
    assert "_user_message_sensor" not in source
    assert "UserMessageSensor()" not in source


def test_others_router_does_not_define_global_other_memory() -> None:
    from magi.api.routers import others as others_router

    source = Path(others_router.__file__).read_text(encoding="utf-8")
    assert "_other_memory" not in source
    assert "OtherMemory(" not in source


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source
