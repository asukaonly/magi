"""Coordinate configuration writes with active embedding rebuilds."""

from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict


_CONFIG_UPDATE_LOCK = asyncio.Lock()
_EMBEDDING_PUBLICATION_LOCK = asyncio.Lock()
_EMBEDDING_EXECUTION_GENERATION = 0


def get_embedding_config_update_lock() -> asyncio.Lock:
    """Return the process-wide lock used by user-facing config writers."""

    return _CONFIG_UPDATE_LOCK


def get_embedding_publication_lock() -> asyncio.Lock:
    """Return the lock that separates vector publication from identity changes."""

    return _EMBEDDING_PUBLICATION_LOCK


def get_embedding_execution_generation() -> int:
    """Return the process-local generation for vector-affecting configuration."""

    return _EMBEDDING_EXECUTION_GENERATION


def _advance_embedding_execution_generation() -> None:
    global _EMBEDDING_EXECUTION_GENERATION
    _EMBEDDING_EXECUTION_GENERATION += 1


def embedding_execution_signature(config: Any) -> Dict[str, Any]:
    """Return the non-secret settings that can change vector execution."""

    memory = getattr(config, "memory", None) or getattr(
        getattr(config, "agent", None), "memory", None
    )
    embedding = getattr(memory, "embedding", None)
    mode = _config_value(getattr(embedding, "mode", "off"))
    signature: Dict[str, Any] = {
        "db_path": str(getattr(memory, "db_path", "") or ""),
        "backend": _config_value(getattr(embedding, "backend", "sqlite_vec")),
        "mode": mode,
        "layers": {
            layer: {
                "enabled": bool(getattr(getattr(memory, layer, None), "enabled", False)),
                "vectors_enabled": bool(
                    getattr(getattr(memory, layer, None), "vectors_enabled", False)
                ),
            }
            for layer in ("l1", "l2", "l3", "l4")
        },
    }

    if mode == "local":
        local = getattr(embedding, "local", None)
        signature["local"] = {
            "model_source": _config_value(getattr(local, "model_source", None)),
            "managed_model_id": str(getattr(local, "managed_model_id", "") or ""),
            "model_dir_path": str(getattr(local, "model_dir_path", "") or ""),
            "variant": str(getattr(local, "variant", "") or ""),
        }
        return signature

    if mode != "remote":
        return signature

    llm = getattr(config, "llm", None)
    selections = getattr(llm, "selections", {}) or {}
    providers = getattr(llm, "providers", {}) or {}
    selection = selections.get("embedding") if isinstance(selections, dict) else None
    provider_id = str(getattr(selection, "provider_id", "") or "")
    provider = providers.get(provider_id) if isinstance(providers, dict) else None
    services = getattr(provider, "services", None)
    provider_embedding = getattr(services, "embedding", None)
    embedding_base_url = str(
        getattr(provider_embedding, "base_url", "") or getattr(provider, "base_url", "") or ""
    )
    signature["remote"] = {
        "selection": {
            "provider_id": provider_id,
            "model": str(getattr(selection, "model", "") or ""),
            "embedding_dimension": getattr(selection, "embedding_dimension", None),
            "capability_override_enabled": bool(
                getattr(selection, "capability_override_enabled", False)
            ),
            "embedding_capability": bool(
                getattr(getattr(selection, "capabilities", None), "embedding", False)
            ),
            "provider_options": _plain_config_value(
                getattr(selection, "provider_options", {}) or {}
            ),
        },
        "provider": {
            "enabled": bool(getattr(provider, "enabled", False)),
            "provider_type": _config_value(getattr(provider, "provider_type", None)),
            "provider_plan": _config_value(getattr(provider, "provider_plan", None)),
            "base_url": embedding_base_url,
            "api_format": str(getattr(provider, "api_format", "") or ""),
            "embedding_service_enabled": bool(getattr(provider_embedding, "enabled", False)),
        },
    }
    return signature


def clone_config_with_update(config: Any, path: str, value: Any) -> Any:
    """Clone a runtime config and apply one existing dot-separated field update."""

    clone = config.model_copy(deep=True) if hasattr(config, "model_copy") else copy.deepcopy(config)
    parts = [part for part in str(path).split(".") if part]
    if not parts:
        raise ValueError("Configuration path cannot be empty")

    current = clone
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Configuration field '{part}' was not found")
            current = current[part]
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            raise AttributeError(f"Configuration field '{part}' was not found")

    final_part = parts[-1]
    if isinstance(current, dict):
        if final_part not in current:
            raise KeyError(f"Configuration field '{final_part}' was not found")
        current[final_part] = value
    elif hasattr(current, final_part):
        setattr(current, final_part, value)
    else:
        raise AttributeError(f"Configuration field '{final_part}' was not found")
    return clone


@asynccontextmanager
async def pause_rebuilds_for_embedding_config_change(
    *,
    current_config: Any,
    proposed_config: Any,
    manager_factory: Callable[[], Any],
) -> AsyncIterator[None]:
    """Pause and drain rebuilds only when a config write changes vector execution."""

    if embedding_execution_signature(current_config) == embedding_execution_signature(
        proposed_config
    ):
        yield
        return

    manager = manager_factory()
    await manager.pause_starts_and_cancel_all()
    try:
        async with get_embedding_publication_lock():
            _advance_embedding_execution_generation()
            try:
                yield
            finally:
                _advance_embedding_execution_generation()
    finally:
        await manager.resume_starts()


def _config_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _plain_config_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {str(key): _plain_config_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_config_value(item) for item in value]
    return _config_value(value)


__all__ = [
    "clone_config_with_update",
    "embedding_execution_signature",
    "get_embedding_config_update_lock",
    "get_embedding_execution_generation",
    "get_embedding_publication_lock",
    "pause_rebuilds_for_embedding_config_change",
]
