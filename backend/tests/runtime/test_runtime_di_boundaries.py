from __future__ import annotations

from pathlib import Path


BACKEND_SRC = Path(__file__).resolve().parents[2] / "src/magi"


def test_bootstrap_backend_does_not_keep_runtime_module_globals() -> None:
    source = (BACKEND_SRC / "bootstrap/backend.py").read_text(encoding="utf-8")

    assert "_runtime_orchestrator" not in source
    assert "_runtime_context" not in source


def test_timeline_and_llm_runtime_do_not_keep_module_level_singletons() -> None:
    source_contrib = (BACKEND_SRC / "awareness/scheduler_contrib.py").read_text(encoding="utf-8")
    timeline_lifecycle = (BACKEND_SRC / "timeline/lifecycle.py").read_text(encoding="utf-8")
    timeline_router = (BACKEND_SRC / "api/routers/timeline.py").read_text(encoding="utf-8")
    memory_lifecycle = (BACKEND_SRC / "memory/lifecycle.py").read_text(encoding="utf-8")
    provider_bridge = (BACKEND_SRC / "llm/provider_bridge/__init__.py").read_text(encoding="utf-8")
    scheduler_service = (BACKEND_SRC / "scheduler/service.py").read_text(encoding="utf-8")

    assert "_source_contrib" not in source_contrib
    assert "def get_source_scheduler_contrib" not in source_contrib
    assert "def set_source_scheduler_contrib" not in source_contrib
    assert "set_source_scheduler_contrib" not in timeline_lifecycle
    assert "get_source_scheduler_contrib" not in timeline_router
    # Phase 5 of D: legacy LLM_CALL_COMPLETED chain deleted entirely.
    assert not (BACKEND_SRC / "llm/usage_events.py").exists()
    assert "configure_llm_usage_event_publisher" not in memory_lifecycle
    assert "_llm_usage_event_publisher" not in provider_bridge
    assert "_active_scheduler_service" not in scheduler_service
    assert "def get_active_scheduler_service" not in scheduler_service


def test_skills_service_access_has_no_module_level_runtime_globals() -> None:
    source = (BACKEND_SRC / "skills/service_access.py").read_text(encoding="utf-8")

    assert "_skill_indexer = None" not in source
    assert "_skill_loader = None" not in source
    assert "_skill_executor = None" not in source
    assert "def get_skill_indexer" not in source
    assert "def get_skill_loader" not in source
    assert "def get_skill_executor" not in source
    assert "def ensure_skill_indexer" not in source
    assert "yaml.safe_load" not in source
    assert "get_config_file_path" not in source


def test_api_and_tools_use_runtime_bindings_instead_of_runtime_getters() -> None:
    memory_router = (BACKEND_SRC / "api/routers/memory/__init__.py").read_text(encoding="utf-8")
    memory_dependencies = (BACKEND_SRC / "api/routers/memory/dependencies.py").read_text(encoding="utf-8")
    timeline_router = (BACKEND_SRC / "api/routers/timeline.py").read_text(encoding="utf-8")
    memory_query_tool = (BACKEND_SRC / "tools/builtin/memory_query_tool.py").read_text(encoding="utf-8")

    assert "from ...agent import get_unified_memory" not in memory_router
    assert "from ...agent import get_memory_integration" not in memory_router
    assert "def get_unified_memory" not in memory_router
    assert "def get_memory_integration" not in memory_router
    assert "from ..routers.memory import get_unified_memory" not in timeline_router
    assert "from ...scheduler import (\n    ScheduledTargetType,\n    get_scheduler_service," not in timeline_router
    assert "from ..agent import get_unified_memory" not in memory_query_tool
    assert "memory.provider" in memory_dependencies
    assert "memory.provider" in timeline_router
    # memory_query_tool resolves memory through the capability port
    # (context.capabilities.memory_query), not a runtime getter or
    # memory.provider import (Phase 2 G+I: memory_query SDK port).
    assert "context.capabilities.memory_query" in memory_query_tool
    assert "require_unified_memory" not in memory_router
    assert "require_unified_memory" not in memory_dependencies
    assert "require_unified_memory" not in timeline_router
    assert "require_hybrid_retrieval_service" not in memory_query_tool
    assert "plugins.provider" in memory_query_tool
    assert "resolve_plugin_manager" not in memory_query_tool
    assert "resolve_plugin_projection_service" in memory_query_tool
    assert "core.runtime_bindings" not in memory_query_tool


def test_timeline_handler_does_not_use_plugin_runtime_globals() -> None:
    source = (BACKEND_SRC / "timeline/handler.py").read_text(encoding="utf-8")

    assert "get_plugin_manager" not in source
    assert "get_source_registry" not in source


def test_tool_capabilities_interaction_port_delegates_to_control_service() -> None:
    source = (BACKEND_SRC / "bootstrap/tool_capabilities.py").read_text(encoding="utf-8")

    assert "ControlAskService" in source
    assert "ControlAskRequest" in source
    assert "open_ask(" not in source
    assert "close_ask(" not in source
    assert "publish_control_ask_requested" not in source
    assert "publish_control_ask_answered" not in source
    assert "get_ask_fanout_callback" not in source


def test_plugin_runtime_uses_container_bindings_instead_of_runtime_globals() -> None:
    plugins_init = (BACKEND_SRC / "plugins/__init__.py").read_text(encoding="utf-8")
    plugins_lifecycle = (BACKEND_SRC / "bootstrap/plugin_system.py").read_text(encoding="utf-8")
    awareness_lifecycle = (BACKEND_SRC / "awareness/lifecycle.py").read_text(encoding="utf-8")
    plugins_router = (BACKEND_SRC / "api/routers/plugins.py").read_text(encoding="utf-8")
    tools_router = (BACKEND_SRC / "api/routers/tools.py").read_text(encoding="utf-8")
    runtime_bindings = (BACKEND_SRC / "core/runtime_bindings.py").read_text(encoding="utf-8")

    assert not (BACKEND_SRC / "plugins/runtime.py").exists()
    assert not (BACKEND_SRC / "plugins/service_access.py").exists()
    assert "get_plugin_manager" not in plugins_init
    assert "get_source_registry" not in plugins_init
    assert "get_action_registry" not in plugins_init
    assert "initialize_plugin_manager" not in plugins_lifecycle
    assert "get_source_registry" not in plugins_lifecycle
    assert "get_action_registry" not in awareness_lifecycle
    assert "get_plugin_manager" not in plugins_router
    assert "reload_plugin_manager" not in plugins_router
    assert "get_plugin_manager" not in tools_router
    assert "plugins.provider" in plugins_router
    assert "plugins.provider" in tools_router
    assert "require_plugin_manager" not in plugins_router
    assert "require_plugin_manager" not in tools_router
    assert "require_action_registry" not in runtime_bindings


def test_plugin_install_flow_lives_in_plugin_service_not_api_helpers() -> None:
    plugins_common = (BACKEND_SRC / "api/routers/plugins_common.py").read_text(
        encoding="utf-8"
    )
    install_routes = (BACKEND_SRC / "api/routers/plugins_install_routes.py").read_text(
        encoding="utf-8"
    )
    core_routes = (BACKEND_SRC / "api/routers/plugins_core_routes.py").read_text(
        encoding="utf-8"
    )
    install_jobs = (BACKEND_SRC / "api/routers/plugins_install_jobs.py").read_text(
        encoding="utf-8"
    )
    registry_routes = (BACKEND_SRC / "api/routers/plugins_registry_routes.py").read_text(
        encoding="utf-8"
    )
    install_service = (BACKEND_SRC / "plugins/install_service.py").read_text(
        encoding="utf-8"
    )

    assert not (BACKEND_SRC / "api/routers/plugins_install_service.py").exists()
    assert "def install_with_closure" not in plugins_common
    assert "def _resolve_install_closure" not in plugins_common
    assert "def _lightweight_install" not in plugins_common
    assert "PluginInstallService" in plugins_common
    assert "_plugin_install_service" in install_routes
    assert "PluginInstallService" in install_jobs
    assert "_plugin_install_service" in registry_routes
    assert "class PluginInstallService" in install_service
    assert "legacy_plugins_module" not in plugins_common
    assert "legacy_plugins_module" not in core_routes
    assert "legacy_plugins_module" not in install_routes
    assert "legacy_plugins_module" not in install_jobs
    assert "legacy_plugins_module" not in registry_routes


def test_runtime_domain_code_does_not_import_core_runtime_package() -> None:
    agent_lifecycle = (BACKEND_SRC / "agent/lifecycle.py").read_text(encoding="utf-8")
    awareness_lifecycle = (BACKEND_SRC / "awareness/lifecycle.py").read_text(encoding="utf-8")
    bootstrap_context = (BACKEND_SRC / "bootstrap/context.py").read_text(encoding="utf-8")
    config_lifecycle = (BACKEND_SRC / "config/lifecycle.py").read_text(encoding="utf-8")
    chat_task_agent = (BACKEND_SRC / "chat/task_agent/chat_task_agent.py").read_text(encoding="utf-8")
    timeline_task_agent = (BACKEND_SRC / "agent/task_agents/timeline_task_agent.py").read_text(encoding="utf-8")
    postprocess_service = (BACKEND_SRC / "chat/task_agent/postprocess_service.py").read_text(encoding="utf-8")
    chat_handlers = (BACKEND_SRC / "agent/task_agents/handlers/handlers.py").read_text(encoding="utf-8")
    worker_manager = (BACKEND_SRC / "agent/workers/worker_manager.py").read_text(encoding="utf-8")
    function_calling = (BACKEND_SRC / "agent/execution/function_calling/__init__.py").read_text(encoding="utf-8")
    task_factory = (BACKEND_SRC / "agent/task_agents/factory.py").read_text(encoding="utf-8")
    event_emitter = (BACKEND_SRC / "awareness/event_emitter.py").read_text(encoding="utf-8")
    awareness_contracts = (BACKEND_SRC / "awareness/contracts.py").read_text(encoding="utf-8")

    assert not (BACKEND_SRC / "core/runtime").exists()
    assert not (BACKEND_SRC / "scheduler/handlers.py").exists()
    assert "from ..core.runtime import AgentRuntime, RouterAgent, TaskAgentManager" not in agent_lifecycle
    assert "from ..core.runtime import SourceHub" not in awareness_lifecycle
    assert "from ..core.runtime import SourceHub, AgentRuntime, TaskAgentManager" not in bootstrap_context
    assert "core.runtime.contracts" not in chat_task_agent
    assert "core.runtime.contracts" not in timeline_task_agent
    assert "core.runtime.types" not in chat_task_agent
    assert "core.runtime.types" not in timeline_task_agent
    assert "core.runtime.task_agent" not in chat_task_agent
    assert "core.runtime.task_agent" not in timeline_task_agent
    assert "core.runtime.contracts" not in postprocess_service
    assert "core.runtime.types" not in postprocess_service
    assert "from ....core.runtime import SourceEvent" not in postprocess_service
    assert "core.runtime_bindings" not in postprocess_service
    assert "core.runtime_bindings" not in chat_handlers
    assert "core.runtime_bindings" not in worker_manager
    assert "core.runtime_bindings" not in function_calling
    assert "core.container" not in worker_manager
    assert "core.runtime.types" not in task_factory
    assert "core.runtime.contracts" not in event_emitter
    assert "agent.runtime.contracts" not in event_emitter
    assert "personality.current_state" not in config_lifecycle
    assert "agent.runtime" in agent_lifecycle
    assert "source_hub" in awareness_lifecycle
    assert "agent.runtime" in bootstrap_context
    assert "class ActionEmissionRecord" not in awareness_contracts
