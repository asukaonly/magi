"""Dependency accessors for memory API route modules."""

from __future__ import annotations

import sys
from typing import Any, Callable, TypeVar

from fastapi import HTTPException, status

from magi.chat import get_chat_read_service as _get_chat_read_service
from magi.agent.orchestration import get_orchestration_store
from magi.core.logger import get_logger
from magi.core.runtime_bindings import (
    get_optional_background_task_manager,
    get_optional_agent_runtime,
    require_runtime_command_queue,
    require_scheduler_service,
)
from magi.llm.provider import get_scenario_llm_pool
from magi.memory.eval_support.answer_synthesis import synthesize_eval_answer
from magi.memory.provider import (
    get_hybrid_retrieval_service,
    get_memory_integration,
    get_unified_memory,
)

from .helpers import memory_t

T = TypeVar("T", bound=Callable[..., Any])

logger = get_logger("magi.api.routers.memory")


def _package_override(name: str, original: T) -> T | None:
    package = sys.modules.get("magi.api.routers.memory")
    if package is None:
        return None
    candidate = getattr(package, name, None)
    if candidate is None or candidate is original:
        return None
    return candidate


def _resolve_unified_memory():
    override = _package_override("_resolve_unified_memory", _resolve_unified_memory)
    if override is not None:
        return override()
    try:
        return get_unified_memory()
    except RuntimeError:
        return None


def _resolve_location_sample_store():
    override = _package_override("_resolve_location_sample_store", _resolve_location_sample_store)
    if override is not None:
        return override()
    try:
        from magi.location.provider import get_location_sample_store

        return get_location_sample_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_store():
    override = _package_override("_resolve_manual_entry_store", _resolve_manual_entry_store)
    if override is not None:
        return override()
    try:
        from magi.memory.provider import get_manual_entry_store

        return get_manual_entry_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_asset_store():
    override = _package_override(
        "_resolve_manual_entry_asset_store", _resolve_manual_entry_asset_store
    )
    if override is not None:
        return override()
    try:
        from magi.memory.provider import get_manual_entry_asset_store

        return get_manual_entry_asset_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_weather_fetcher():
    override = _package_override(
        "_resolve_manual_entry_weather_fetcher", _resolve_manual_entry_weather_fetcher
    )
    if override is not None:
        return override()
    try:
        from magi.memory.provider import get_manual_entry_weather_fetcher

        return get_manual_entry_weather_fetcher()
    except RuntimeError:
        return None


def _resolve_mcp_resource_cache():
    override = _package_override(
        "_resolve_mcp_resource_cache",
        _resolve_mcp_resource_cache,
    )
    if override is not None:
        return override()
    from magi.mcp.resource_cache import get_default_cache

    return get_default_cache()


def _resolve_tool_registry():
    override = _package_override(
        "_resolve_tool_registry",
        _resolve_tool_registry,
    )
    if override is not None:
        return override()
    from magi.tools import tool_registry

    return tool_registry


def _resolve_memory_integration():
    override = _package_override("_resolve_memory_integration", _resolve_memory_integration)
    if override is not None:
        return override()
    try:
        return get_memory_integration()
    except RuntimeError:
        return None


def _resolve_hybrid_retrieval_service():
    override = _package_override(
        "_resolve_hybrid_retrieval_service", _resolve_hybrid_retrieval_service
    )
    if override is not None:
        return override()
    try:
        return get_hybrid_retrieval_service()
    except RuntimeError:
        return None


def _resolve_task_agent_manager():
    override = _package_override(
        "_resolve_task_agent_manager",
        _resolve_task_agent_manager,
    )
    if override is not None:
        return override()
    runtime = get_optional_agent_runtime()
    if runtime is None:
        return None
    return runtime.get_task_agent_manager()


def _resolve_background_task_manager():
    override = _package_override(
        "_resolve_background_task_manager",
        _resolve_background_task_manager,
    )
    if override is not None:
        return override()
    return get_optional_background_task_manager()


def _resolve_runtime_command_queue():
    override = _package_override(
        "_resolve_runtime_command_queue",
        _resolve_runtime_command_queue,
    )
    if override is not None:
        return override()
    return require_runtime_command_queue()


def _resolve_scheduler_service():
    override = _package_override(
        "_resolve_scheduler_service",
        _resolve_scheduler_service,
    )
    if override is not None:
        return override()
    try:
        return require_scheduler_service()
    except RuntimeError:
        return None


def _resolve_sensor_hub():
    override = _package_override("_resolve_sensor_hub", _resolve_sensor_hub)
    if override is not None:
        return override()
    runtime = get_optional_agent_runtime()
    if runtime is None:
        return None
    return runtime.get_sensor_hub()


def _resolve_outreach_service():
    override = _package_override(
        "_resolve_outreach_service",
        _resolve_outreach_service,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    return getattr(getattr(context, "outreach", None), "service", None)


def _resolve_channel_session_mapper():
    override = _package_override(
        "_resolve_channel_session_mapper",
        _resolve_channel_session_mapper,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    channels_module = getattr(getattr(context, "channels", None), "module", None)
    return getattr(channels_module, "session_mapper", None)


def _resolve_channels_module():
    override = _package_override(
        "_resolve_channels_module",
        _resolve_channels_module,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    return getattr(getattr(context, "channels", None), "module", None)


def _resolve_control_user_content_clear():
    override = _package_override(
        "_resolve_control_user_content_clear",
        _resolve_control_user_content_clear,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    control_module = getattr(getattr(context, "control_plane", None), "module", None)
    wiring = getattr(control_module, "wiring", None)
    coordinator = getattr(wiring, "user_content_clear", None)
    if not callable(getattr(coordinator, "user_content_clear_boundary", None)):
        return None
    return coordinator


def _resolve_plugin_user_content_clear():
    override = _package_override(
        "_resolve_plugin_user_content_clear",
        _resolve_plugin_user_content_clear,
    )
    if override is not None:
        return override()
    try:
        from magi.plugins.provider import (
            resolve_plugin_user_content_clear_coordinator,
        )

        coordinator = resolve_plugin_user_content_clear_coordinator()
    except RuntimeError:
        return None
    if not callable(getattr(coordinator, "user_content_clear_boundary", None)):
        return None
    return coordinator


def _resolve_self_memory():
    override = _package_override("_resolve_self_memory", _resolve_self_memory)
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    return getattr(getattr(context, "personality", None), "self_memory", None)


def _resolve_chat_portrait_service():
    override = _package_override(
        "_resolve_chat_portrait_service",
        _resolve_chat_portrait_service,
    )
    if override is not None:
        return override()
    try:
        from magi.core.runtime_bindings import require_chat_portrait_service

        service = require_chat_portrait_service()
    except RuntimeError:
        return None
    if not callable(getattr(service, "global_data_clear_boundary", None)):
        return None
    return service


def _resolve_runtime_trace_store():
    override = _package_override(
        "_resolve_runtime_trace_store",
        _resolve_runtime_trace_store,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    store = getattr(getattr(context, "runtime_trace", None), "store", None)
    if not callable(getattr(store, "plugin_ingress_global_clear_boundary", None)):
        return None
    return store


def _resolve_runtime_trace_subscriber():
    override = _package_override(
        "_resolve_runtime_trace_subscriber",
        _resolve_runtime_trace_subscriber,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    subscriber = getattr(
        getattr(context, "runtime_trace", None),
        "subscriber",
        None,
    )
    if not callable(getattr(subscriber, "user_content_clear_boundary", None)):
        return None
    return subscriber


def _resolve_llm_usage_subscriber():
    override = _package_override(
        "_resolve_llm_usage_subscriber",
        _resolve_llm_usage_subscriber,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    subscriber = getattr(getattr(context, "llm", None), "llm_usage_subscriber", None)
    if not callable(getattr(subscriber, "user_content_clear_boundary", None)):
        return None
    return subscriber


def _resolve_llm_usage_store():
    override = _package_override(
        "_resolve_llm_usage_store",
        _resolve_llm_usage_store,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container

        context = get_container().runtime_bootstrap_context()
    except Exception:
        return None
    store = getattr(getattr(context, "llm", None), "llm_usage_store", None)
    if not callable(getattr(store, "clear_user_content", None)):
        return None
    return store


def _resolve_legacy_user_content_clearer():
    override = _package_override(
        "_resolve_legacy_user_content_clearer",
        _resolve_legacy_user_content_clearer,
    )
    if override is not None:
        return override()
    try:
        from magi.core.container import get_container
        from magi.memory.legacy_user_content import clear_legacy_user_content

        context = get_container().runtime_bootstrap_context()
        runtime_paths = context.core.runtime_paths
    except Exception:
        return None
    if runtime_paths is None:
        return None

    def clear() -> int:
        return clear_legacy_user_content(runtime_paths)

    return clear


def _resolve_orchestration_store():
    override = _package_override(
        "_resolve_orchestration_store",
        _resolve_orchestration_store,
    )
    if override is not None:
        return override()
    return get_orchestration_store()


def _resolve_batch_store():
    override = _package_override(
        "_resolve_batch_store",
        _resolve_batch_store,
    )
    if override is not None:
        return override()
    from magi.agent.batch.store import default_batch_store

    return default_batch_store()


def _resolve_scenario_llm_pool():
    override = _package_override("_resolve_scenario_llm_pool", _resolve_scenario_llm_pool)
    if override is not None:
        return override()
    try:
        return get_scenario_llm_pool()
    except RuntimeError:
        return None


def get_chat_read_service():
    override = _package_override("get_chat_read_service", get_chat_read_service)
    if override is not None:
        return override()
    return _get_chat_read_service()


async def _synthesize_eval_answer(**kwargs: Any) -> tuple[str, dict[str, Any]]:
    llm_pool = _resolve_scenario_llm_pool()
    if llm_pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=memory_t(
                "memory.errors.scenario_llm_pool_uninitialized",
                "Scenario LLM pool is not initialized",
            ),
        )
    return await synthesize_eval_answer(
        **kwargs,
        llm_pool=llm_pool,
        log=logger,
    )
