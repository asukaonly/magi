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


def test_bootstrap_and_agent_exports_do_not_keep_chat_runtime_aliases() -> None:
    bootstrap_source = (BACKEND_SRC / "bootstrap/__init__.py").read_text(encoding="utf-8")
    backend_source = (BACKEND_SRC / "bootstrap/backend.py").read_text(encoding="utf-8")
    agent_source = (BACKEND_SRC / "agent/__init__.py").read_text(encoding="utf-8")
    config_router = (BACKEND_SRC / "api/routers/config.py").read_text(encoding="utf-8")

    assert "initialize_chat_agent" not in bootstrap_source
    assert "shutdown_chat_agent" not in bootstrap_source
    assert "get_master_agent" not in bootstrap_source
    assert "initialize_chat_agent" not in backend_source
    assert "shutdown_chat_agent" not in backend_source
    assert "get_master_agent" not in backend_source
    assert "initialize_chat_agent" not in agent_source
    assert "shutdown_chat_agent" not in agent_source
    assert "from ...bootstrap import initialize_chat_agent" not in config_router


def test_agent_execution_package_uses_function_calling_orchestrator_name() -> None:
    execution_init = (BACKEND_SRC / "agent/execution/__init__.py").read_text(encoding="utf-8")
    function_calling_source = (BACKEND_SRC / "agent/execution/function_calling.py").read_text(encoding="utf-8")
    chat_agent_source = (BACKEND_SRC / "agent/task_agents/chat_task_agent.py").read_text(encoding="utf-8")
    worker_manager_source = (BACKEND_SRC / "agent/workers/worker_manager.py").read_text(encoding="utf-8")
    chat_handlers_source = (BACKEND_SRC / "agent/task_agents/chat/handlers.py").read_text(encoding="utf-8")
    skills_subagent_source = (BACKEND_SRC / "skills/subagent.py").read_text(encoding="utf-8")

    assert "FunctionCallingExecutor" not in execution_init
    assert "class FunctionCallingExecutor" not in function_calling_source
    assert "FunctionCallingExecutor" not in chat_agent_source
    assert "FunctionCallingExecutor" not in worker_manager_source
    assert "function_calling_executor" not in chat_agent_source
    assert "function_calling_executor" not in chat_handlers_source
    assert "_function_calling_executor" not in skills_subagent_source
    assert "FunctionCallingOrchestrator" in execution_init
    assert "function_calling_orchestrator" in chat_agent_source
    assert "function_calling_orchestrator" in chat_handlers_source
    assert "_function_calling_orchestrator" in skills_subagent_source


def test_skills_package_uses_skill_runner_name() -> None:
    skills_init = (BACKEND_SRC / "skills/__init__.py").read_text(encoding="utf-8")
    skills_source = (BACKEND_SRC / "skills/runner.py").read_text(encoding="utf-8")
    skills_service_access = (BACKEND_SRC / "skills/service_access.py").read_text(encoding="utf-8")
    tools_init = (BACKEND_SRC / "tools/__init__.py").read_text(encoding="utf-8")

    assert "SkillExecutor" not in skills_init
    assert "class SkillExecutor" not in skills_source
    assert "SkillExecutor" not in skills_service_access
    assert "SkillExecutor" not in tools_init
    assert "SkillRunner" in skills_init
    assert not (BACKEND_SRC / "skills/executor.py").exists()


def test_backend_docs_do_not_reference_removed_runtime_bootstrap_path() -> None:
    docs_root = BACKEND_SRC.parents[1] / "docs"
    memory_design = (docs_root / "memory-system-design.md").read_text(encoding="utf-8")
    memory_plan = (docs_root / "memory-system-execution-plan.md").read_text(encoding="utf-8")

    assert "runtime/bootstrap.py" not in memory_design
    assert "runtime/bootstrap.py" not in memory_plan


def test_shared_skills_runtime_uses_skill_runner_binding_name() -> None:
    bootstrap_context = (BACKEND_SRC / "bootstrap/context.py").read_text(encoding="utf-8")
    service_access = (BACKEND_SRC / "skills/service_access.py").read_text(encoding="utf-8")
    lifecycle_source = (BACKEND_SRC / "skills/lifecycle.py").read_text(encoding="utf-8")
    container_source = (BACKEND_SRC / "core/container.py").read_text(encoding="utf-8")
    exports_source = (BACKEND_SRC / "bootstrap/exports.py").read_text(encoding="utf-8")
    runtime_bindings = (BACKEND_SRC / "core/runtime_bindings.py").read_text(encoding="utf-8")
    api_services = (BACKEND_SRC / "api/services/__init__.py").read_text(encoding="utf-8")
    skills_router = (BACKEND_SRC / "api/routers/skills.py").read_text(encoding="utf-8")

    assert "skill_executor" not in bootstrap_context
    assert "skill_executor" not in service_access
    assert "skill_executor" not in lifecycle_source
    assert "skill_executor" not in container_source
    assert "skill_executor" not in exports_source
    assert "require_skill_executor" not in runtime_bindings
    assert "skill_executor" not in api_services
    assert "skill_executor" not in skills_router
    assert "skill_runner" in bootstrap_context
    assert "skill_runner" in service_access
    assert "skill_runner" in lifecycle_source
    assert "skill_runner" in container_source
    assert "skill_runner" in exports_source
    assert "require_skill_runner" in runtime_bindings


def test_plugin_runtime_uses_container_bindings_instead_of_runtime_globals() -> None:
    plugins_init = (BACKEND_SRC / "plugins/__init__.py").read_text(encoding="utf-8")
    plugins_lifecycle = (BACKEND_SRC / "plugins/lifecycle.py").read_text(encoding="utf-8")
    awareness_lifecycle = (BACKEND_SRC / "awareness/lifecycle.py").read_text(encoding="utf-8")
    plugins_router = (BACKEND_SRC / "api/routers/plugins.py").read_text(encoding="utf-8")
    tools_router = (BACKEND_SRC / "api/routers/tools.py").read_text(encoding="utf-8")
    runtime_bindings = (BACKEND_SRC / "core/runtime_bindings.py").read_text(encoding="utf-8")

    assert not (BACKEND_SRC / "plugins/runtime.py").exists()
    assert "get_plugin_manager" not in plugins_init
    assert "get_sensor_registry" not in plugins_init
    assert "get_action_registry" not in plugins_init
    assert "initialize_plugin_manager" not in plugins_lifecycle
    assert "get_sensor_registry" not in plugins_lifecycle
    assert "get_action_registry" not in awareness_lifecycle
    assert "get_plugin_manager" not in plugins_router
    assert "reload_plugin_manager" not in plugins_router
    assert "get_plugin_manager" not in tools_router
    assert "require_plugin_manager" in plugins_router
    assert "require_plugin_manager" in tools_router
    assert "require_action_registry" in runtime_bindings


def test_backend_app_does_not_forward_websocket_bridge_retry_default() -> None:
    backend_app_source = (BACKEND_SRC / "backend_app.py").read_text(encoding="utf-8")

    assert "WEBSOCKET_BRIDGE_RETRY_INTERVAL_SECONDS" not in backend_app_source
    assert "retry_interval_seconds=" not in backend_app_source
    assert "WebSocketBridgeLifecycleModule(app)" in backend_app_source