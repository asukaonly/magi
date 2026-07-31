"""Shared LLM provider testing, discovery, and registry loading."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from ... import i18n as core_i18n
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    build_default_llm_provider_registry,
    find_provider_meta,
    load_llm_provider_registry,
    resolve_provider_plan_meta,
)
from ...config.models import LLMProviderSettings
from ...config import get_config
from ...core.logger import get_logger
from ...utils.log_redaction import redact_log_value, refresh_known_log_secrets
from ...llm import LLMProviderBridge, create_llm_adapter
from ...llm.draft import build_adapter_from_provider
from ...utils.packaged_paths import get_backend_root

logger = get_logger(__name__)


def _sanitize_log_value(value: Any) -> Any:
    return redact_log_value(value)


# ── Shared request/response models ──────────────────────────────────────


class DiscoverLLMModelsRequestModel(BaseModel):
    provider_type: str = Field(default="custom")
    base_url: str
    api_key: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default="openai")

    @model_validator(mode="before")
    @classmethod
    def _register_secrets_before_validation(cls, value: Any) -> Any:
        refresh_known_log_secrets(value)
        return value


class DiscoverLLMModelsResponseModel(BaseModel):
    models: List[str] = Field(default_factory=list)
    default_model: Optional[str] = Field(default=None)


class DiscoverLLMModelsApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[DiscoverLLMModelsResponseModel] = None


class TestLLMProviderRequestModel(BaseModel):
    provider_id: str = Field(default="openai")
    provider: Any  # LLMProviderConfigModel (defined in config router)
    model: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _register_secrets_before_validation(cls, value: Any) -> Any:
        refresh_known_log_secrets(value)
        return value


class TestLLMProviderResponseModel(BaseModel):
    model: str
    latency_ms: int
    preview: str = Field(default="")


class TestLLMProviderApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[TestLLMProviderResponseModel] = None


# ── Registry loading ────────────────────────────────────────────────────


def _llm_provider_registry_path() -> Path:
    return get_backend_root() / "configs" / "llm_providers.yaml"


def _default_llm_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        _llm_provider_registry_path(),
        fallback=build_default_llm_provider_registry(),
    )


def get_llm_provider_registry() -> LLMProviderRegistryModel:
    """Load the LLM provider registry from disk with built-in fallback."""
    return _default_llm_provider_registry()


# ── Model discovery ─────────────────────────────────────────────────────


async def discover_openai_compatible_models(
    base_url: str,
    api_key: Optional[str],
    api_format: Optional[str],
) -> List[str]:
    """Discover models from an OpenAI-compatible /models endpoint."""
    if api_format not in (None, "", "openai"):
        raise HTTPException(
            status_code=400,
            detail=core_i18n.t(
                "llm.providers.models.unsupported_discovery_format",
                fallback="Unsupported model discovery format",
            ),
        )

    endpoint = base_url.rstrip("/") + "/models"
    headers: Dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    proxy_url = get_config().network.proxy_url()
    # aiohttp only supports HTTP proxies natively; skip SOCKS proxy URLs.
    if proxy_url and proxy_url.startswith("socks"):
        proxy_url = None
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(endpoint, headers=headers, proxy=proxy_url) as response:
                if response.status >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=core_i18n.t(
                            "llm.providers.models.discovery_request_failed_status",
                            fallback="Model discovery request failed with status {status}",
                            status=response.status,
                        ),
                    )
                payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=core_i18n.t(
                "llm.providers.models.discovery_failed",
                fallback="Failed to discover models: {error}",
                error=str(exc),
            ),
        ) from exc

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise HTTPException(
            status_code=502,
            detail=core_i18n.t(
                "llm.providers.models.discovery_invalid_payload",
                fallback="Model discovery response payload is invalid",
            ),
        )

    models: List[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                models.append(model_id)
    return models


# ── Provider connection testing ──────────────────────────────────────────


async def test_llm_provider_connection(
    provider_id: str,
    provider: Any,
    model: str,
) -> Dict[str, Any]:
    """Test an LLM provider connection with a simple chat call."""
    logger.info(
        "llm_provider_test_started",
        provider_id=provider_id,
        model=model,
        provider=_sanitize_log_value(provider),
    )
    runtime_provider = LLMProviderSettings.model_validate(provider.model_dump())
    provider_type = str(
        getattr(
            getattr(runtime_provider, "provider_type", ""), "value", runtime_provider.provider_type
        )
        or provider_id
    )
    registry_meta = find_provider_meta(get_llm_provider_registry(), provider_type)
    effective_meta = (
        resolve_provider_plan_meta(registry_meta, runtime_provider.provider_plan)
        if registry_meta is not None
        else None
    )
    adapter = build_adapter_from_provider(
        runtime_provider,
        model=model,
        default_base_url=effective_meta.default_base_url if effective_meta else None,
        adapter_factory=create_llm_adapter,
    )
    bridge = LLMProviderBridge(adapter)
    started_at = time.perf_counter()
    preview = await bridge.chat(
        system_prompt="You are a connection test assistant. Reply briefly.",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32,
        temperature=0.1,
        disable_thinking=True,
        event_context={
            "request_kind": "config:provider_test",
            "agent_id": "config_provider_test",
            "surface": "config_provider_test",
            "provider_id": provider_id,
        },
    )
    result = {
        "model": model,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "preview": preview[:120].strip(),
    }
    logger.info(
        "llm_provider_test_succeeded",
        provider_id=provider_id,
        model=model,
        latency_ms=result["latency_ms"],
        preview=result["preview"],
    )
    return result
