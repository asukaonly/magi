"""Dependency accessors for memory API route modules."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from magi.api.runtime_dependencies import get_api_runtime_dependencies, require_chat_read_service
from magi.core.logger import get_logger
from magi.agent.background.provider import get_optional_background_task_manager
from magi.core.runtime_bindings import get_optional_agent_runtime, require_runtime_command_queue
from magi.scheduler.provider import require_scheduler_service
from magi.llm.provider import get_scenario_llm_pool
from magi.memory.eval_support.answer_synthesis import synthesize_eval_answer
from magi.memory.provider import (
    get_history_import_service,
    get_hybrid_retrieval_service,
    get_memory_integration,
    get_unified_memory,
)

from .helpers import memory_t


logger = get_logger("magi.api.routers.memory")


def get_chat_read_service():
    return require_chat_read_service()


def _resolve_unified_memory():
    try:
        return get_unified_memory()
    except RuntimeError:
        return None


def _resolve_location_sample_store():
    try:
        from magi.location.provider import get_location_sample_store

        return get_location_sample_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_store():
    try:
        from magi.memory.provider import get_manual_entry_store

        return get_manual_entry_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_asset_store():
    try:
        from magi.memory.provider import get_manual_entry_asset_store

        return get_manual_entry_asset_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_weather_fetcher():
    try:
        from magi.memory.provider import get_manual_entry_weather_fetcher

        return get_manual_entry_weather_fetcher()
    except RuntimeError:
        return None


def _resolve_history_import_service():
    try:
        service = get_history_import_service()
    except RuntimeError:
        return None
    if not callable(getattr(service, "user_content_clear_boundary", None)):
        return None
    return service


def _resolve_mcp_resource_cache():
    from magi.mcp.resource_cache import get_default_cache
    return get_default_cache()


def _resolve_tool_registry():
    from magi.tools import tool_registry
    return tool_registry


def _resolve_memory_integration():
    try:
        return get_memory_integration()
    except RuntimeError:
        return None


def _resolve_hybrid_retrieval_service():
    try:
        return get_hybrid_retrieval_service()
    except RuntimeError:
        return None


def _resolve_task_agent_manager():
    runtime = get_optional_agent_runtime()
    if runtime is None:
        return None
    return runtime.get_task_agent_manager()


def _resolve_background_task_manager():
    return get_optional_background_task_manager()


def _resolve_runtime_command_queue():
    return require_runtime_command_queue()


def _resolve_scheduler_service():
    try:
        return require_scheduler_service()
    except RuntimeError:
        return None


def _resolve_source_hub():
    runtime = get_optional_agent_runtime()
    if runtime is None:
        return None
    return runtime.get_source_hub()


def _resolve_outreach_service():
    return get_api_runtime_dependencies().outreach_service


def _resolve_channel_session_mapper():
    module = get_api_runtime_dependencies().channels_module
    return module.session_mapper if module is not None else None


def _resolve_channels_module():
    return get_api_runtime_dependencies().channels_module


def _resolve_control_user_content_clear():
    return get_api_runtime_dependencies().control_user_content_clear


def _resolve_plugin_user_content_clear():
    return get_api_runtime_dependencies().plugin_user_content_clear


def _resolve_chat_memory_projection_clear():
    return get_api_runtime_dependencies().chat_memory_projection_clear


def _resolve_self_memory():
    return get_api_runtime_dependencies().self_memory


def _resolve_chat_portrait_service():
    try:
        from magi.api.runtime_dependencies import require_chat_portrait_service

        service = require_chat_portrait_service()
    except RuntimeError:
        return None
    if not callable(getattr(service, "global_data_clear_boundary", None)):
        return None
    return service


def _resolve_runtime_trace_store():
    return get_api_runtime_dependencies().runtime_trace_store


def _resolve_runtime_trace_subscriber():
    return get_api_runtime_dependencies().runtime_trace_subscriber


def _resolve_llm_usage_subscriber():
    return get_api_runtime_dependencies().llm_usage_subscriber


def _resolve_llm_usage_store():
    return get_api_runtime_dependencies().llm_usage_store


def _resolve_batch_store():
    from magi.agent.batch.store import default_batch_store
    return default_batch_store()


def _resolve_scenario_llm_pool():
    try:
        return get_scenario_llm_pool()
    except RuntimeError:
        return None


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
