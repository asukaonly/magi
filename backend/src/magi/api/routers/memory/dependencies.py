"""Dependency accessors for memory API route modules."""

from __future__ import annotations

import sys
from typing import Any, Callable, TypeVar

from magi.chat import get_chat_read_service as _get_chat_read_service
from magi.core.logger import get_logger
from magi.llm.provider import get_scenario_llm_pool
from magi.memory.provider import get_hybrid_retrieval_service, get_memory_integration, get_unified_memory

from .eval.answering import synthesize_eval_answer

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
    override = _package_override("_resolve_manual_entry_asset_store", _resolve_manual_entry_asset_store)
    if override is not None:
        return override()
    try:
        from magi.memory.provider import get_manual_entry_asset_store
        return get_manual_entry_asset_store()
    except RuntimeError:
        return None


def _resolve_manual_entry_weather_fetcher():
    override = _package_override("_resolve_manual_entry_weather_fetcher", _resolve_manual_entry_weather_fetcher)
    if override is not None:
        return override()
    try:
        from magi.memory.provider import get_manual_entry_weather_fetcher
        return get_manual_entry_weather_fetcher()
    except RuntimeError:
        return None


def _resolve_memory_integration():
    override = _package_override("_resolve_memory_integration", _resolve_memory_integration)
    if override is not None:
        return override()
    try:
        return get_memory_integration()
    except RuntimeError:
        return None


def _resolve_hybrid_retrieval_service():
    override = _package_override("_resolve_hybrid_retrieval_service", _resolve_hybrid_retrieval_service)
    if override is not None:
        return override()
    try:
        return get_hybrid_retrieval_service()
    except RuntimeError:
        return None


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
    return await synthesize_eval_answer(
        **kwargs,
        llm_pool=_resolve_scenario_llm_pool(),
        log=logger,
    )
