from __future__ import annotations

from pathlib import Path


def test_messages_router_does_not_define_global_user_message_source() -> None:
    from magi.api.routers import messages as messages_router

    source = Path(messages_router.__file__).read_text(encoding="utf-8")
    assert "_user_message_source:" not in source
    assert "global _user_message_source" not in source
    assert "UserMessageSource()" not in source


def test_api_services_module_does_not_reexport_runtime_globals() -> None:
    from magi.api import services as api_services

    source = Path(api_services.__file__).read_text(encoding="utf-8")
    assert "events.service_access" not in source
    assert "skills.service_access" not in source
    assert "personality.current_state" not in source


def test_api_service_helpers_do_not_probe_container_directly() -> None:
    from magi.api import services as api_services
    from magi.runtime_trace.chat_trace import read_service as chat_trace_read_service_module
    from magi.chat import read_service as chat_read_service_module

    api_services_dir = Path(api_services.__file__).resolve().parent
    chat_read_service = Path(chat_read_service_module.__file__).read_text(encoding="utf-8")
    chat_trace_read_service = Path(chat_trace_read_service_module.__file__).read_text(encoding="utf-8")

    assert "get_container()" not in chat_read_service
    assert "get_container()" not in chat_trace_read_service
    assert "\n_chat_read_service" not in chat_read_service
    assert "global _chat_read_service" not in chat_read_service
    assert "\n_chat_trace_read_service" not in chat_trace_read_service
    assert "global _chat_trace_read_service" not in chat_trace_read_service
    assert not (api_services_dir / "chat_read_service.py").exists()
    assert not (api_services_dir / "user_message_source_service.py").exists()
    assert not (api_services_dir / "message_bus_service.py").exists()
    assert not (api_services_dir / "other_memory_service.py").exists()


def test_personality_config_router_does_not_read_builtin_preset_files() -> None:
    from magi.api.routers import personality_config as personality_config_router

    source = Path(personality_config_router.__file__).read_text(encoding="utf-8")

    assert "_get_builtin_personalities_dir" not in source
    assert "_load_builtin_personality" not in source
    assert "backend/personalities" not in source
    assert ".glob(\"*.json\")" not in source
