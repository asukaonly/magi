from __future__ import annotations

from pathlib import Path


def test_messages_router_does_not_define_global_user_message_sensor() -> None:
    from magi.api.routers import messages as messages_router

    source = Path(messages_router.__file__).read_text(encoding="utf-8")
    assert "_user_message_sensor:" not in source
    assert "global _user_message_sensor" not in source
    assert "UserMessageSensor()" not in source


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source


def test_api_service_helpers_do_not_probe_container_directly() -> None:
    chat_read_service = Path("/Users/asuka/code/magi/backend/src/magi/chat/read_service.py").read_text(encoding="utf-8")
    chat_trace_read_service = Path("/Users/asuka/code/magi/backend/src/magi/api/services/chat_trace_read_service.py").read_text(encoding="utf-8")

    assert "get_container()" not in chat_read_service
    assert "get_container()" not in chat_trace_read_service
    assert not Path("/Users/asuka/code/magi/backend/src/magi/api/services/chat_read_service.py").exists()
    assert not Path("/Users/asuka/code/magi/backend/src/magi/api/services/user_message_sensor_service.py").exists()
    assert not Path("/Users/asuka/code/magi/backend/src/magi/api/services/message_bus_service.py").exists()
    assert not Path("/Users/asuka/code/magi/backend/src/magi/api/services/other_memory_service.py").exists()
