from __future__ import annotations

from pathlib import Path


BACKEND_SRC = Path(__file__).resolve().parents[2] / "src/magi"


def test_bootstrap_backend_does_not_keep_runtime_module_globals() -> None:
    source = (BACKEND_SRC / "bootstrap/backend.py").read_text(encoding="utf-8")

    assert "_runtime_orchestrator" not in source
    assert "_runtime_context" not in source


def test_bootstrap_package_no_longer_exports_runtime_getters() -> None:
    source = (BACKEND_SRC / "bootstrap/__init__.py").read_text(encoding="utf-8")

    assert '"get_agent_runtime"' not in source
    assert '"get_scheduler_service"' not in source
    assert '"get_unified_memory"' not in source
    assert '"get_memory_integration"' not in source


def test_events_service_access_has_no_global_fallback() -> None:
    source = (BACKEND_SRC / "events/service_access.py").read_text(encoding="utf-8")

    assert "_message_bus: Any = None" not in source
    assert "def set_message_bus" not in source


def test_skills_service_access_has_no_module_level_runtime_globals() -> None:
    source = (BACKEND_SRC / "skills/service_access.py").read_text(encoding="utf-8")

    assert "_skill_indexer = None" not in source
    assert "_skill_loader = None" not in source
    assert "_skill_executor = None" not in source
    assert "def get_skill_indexer" not in source
    assert "def get_skill_loader" not in source
    assert "def get_skill_executor" not in source
    assert "def ensure_skill_indexer" not in source


def test_scheduler_runtime_shim_is_removed() -> None:
    assert not (BACKEND_SRC / "scheduler/runtime.py").exists()


def test_api_and_tools_use_runtime_bindings_instead_of_runtime_getters() -> None:
    memory_router = (BACKEND_SRC / "api/routers/memory.py").read_text(encoding="utf-8")
    timeline_router = (BACKEND_SRC / "api/routers/timeline.py").read_text(encoding="utf-8")
    websocket_handlers = (BACKEND_SRC / "websocket/handlers.py").read_text(encoding="utf-8")
    memory_query_tool = (BACKEND_SRC / "tools/memory_query.py").read_text(encoding="utf-8")

    assert "from ...agent import get_unified_memory" not in memory_router
    assert "from ...agent import get_memory_integration" not in memory_router
    assert "def get_unified_memory" not in memory_router
    assert "def get_memory_integration" not in memory_router
    assert "from ..routers.memory import get_unified_memory" not in timeline_router
    assert "from ...scheduler import (\n    ScheduledTargetType,\n    get_scheduler_service," not in timeline_router
    assert "from ..agent import get_unified_memory" not in memory_query_tool
    assert "from ..agent import get_agent_runtime" not in websocket_handlers
    assert "core.runtime_bindings" in memory_router
    assert "core.runtime_bindings" in timeline_router
    assert "core.runtime_bindings" in websocket_handlers
    assert "core.runtime_bindings" in memory_query_tool


def test_timeline_handler_does_not_use_plugin_runtime_globals() -> None:
    source = (BACKEND_SRC / "timeline/handler.py").read_text(encoding="utf-8")

    assert "get_plugin_manager" not in source
    assert "get_sensor_registry" not in source