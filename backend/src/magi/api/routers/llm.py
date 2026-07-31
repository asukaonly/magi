"""Dedicated LLM catalog and provider utility APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import i18n as core_i18n
from ...config import get_config
from ...config.llm_registry import (
    LLMCustomProviderMetaModel,
    LLMProviderCatalogEntryModel,
    build_provider_catalog,
    find_provider_meta,
    resolve_provider_plan_meta,
)
from ...config.models import LLMProviderSettings
from ...core.logger import get_logger
from ..services.config_secrets import normalize_masked_llm_provider_secrets
from .config_schemas import (
    LLMProviderConfigModel,
    LLMProviderConnectionConfigModel,
    LLMProviderServicesConfigModel,
)
from ..services.llm_testing_service import (
    DiscoverLLMModelsApiResponseModel,
    DiscoverLLMModelsResponseModel,
    DiscoverLLMModelsRequestModel,
    TestLLMProviderApiResponseModel,
    TestLLMProviderResponseModel,
    TestLLMProviderRequestModel,
    get_llm_provider_registry as _load_llm_provider_registry,
    discover_openai_compatible_models as _discover_openai_compatible_models,
    test_llm_provider_connection as _test_llm_provider_connection,
)

llm_router = APIRouter()
logger = get_logger(__name__)


class LLMProviderCatalogDataModel(BaseModel):
    providers: list[LLMProviderCatalogEntryModel] = Field(default_factory=list)


class LLMProviderCatalogResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[LLMProviderCatalogDataModel] = None


class LLMProviderCatalogResolveRequestModel(BaseModel):
    providers: dict[str, LLMProviderConfigModel] = Field(default_factory=dict)


class LLMCustomProviderTemplateDataModel(BaseModel):
    template: LLMCustomProviderMetaModel
    defaults: LLMProviderConfigModel


class LLMCustomProviderTemplateResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[LLMCustomProviderTemplateDataModel] = None


def _build_custom_provider_defaults(
    registry_meta: LLMCustomProviderMetaModel,
) -> LLMProviderConfigModel:
    return LLMProviderConfigModel(
        enabled=True,
        provider_type="custom",
        display_name=registry_meta.display_name or "",
        api_key="",
        base_url="",
        services=LLMProviderServicesConfigModel(
            chat=LLMProviderConnectionConfigModel(enabled=True, api_key="", base_url=""),
            embedding=LLMProviderConnectionConfigModel(enabled=False, api_key="", base_url=""),
        ),
        api_format="openai",
        custom_models=[],
        custom_default_model="",
        model_metadata_overrides={},
    )


@llm_router.get("/providers/catalog", response_model=LLMProviderCatalogResponseModel)
async def get_llm_provider_catalog():
    registry = _load_llm_provider_registry()
    runtime_config = get_config()
    catalog = build_provider_catalog(
        registry,
        provider_settings_by_id=dict(getattr(runtime_config.llm, "providers", {}) or {}),
    )
    return LLMProviderCatalogResponseModel(
        success=True,
        message=core_i18n.t("llm.providers.catalog.loaded", fallback="LLM provider catalog loaded"),
        data=LLMProviderCatalogDataModel(providers=catalog),
    )


@llm_router.post("/providers/catalog", response_model=LLMProviderCatalogResponseModel)
async def resolve_llm_provider_catalog(payload: LLMProviderCatalogResolveRequestModel):
    registry = _load_llm_provider_registry()
    provider_settings_by_id = {
        provider_id: LLMProviderSettings.model_validate(provider.model_dump(mode="json"))
        for provider_id, provider in payload.providers.items()
    }
    catalog = build_provider_catalog(
        registry,
        provider_settings_by_id=provider_settings_by_id,
    )
    return LLMProviderCatalogResponseModel(
        success=True,
        message=core_i18n.t(
            "llm.providers.catalog.resolved", fallback="LLM provider catalog resolved"
        ),
        data=LLMProviderCatalogDataModel(providers=catalog),
    )


@llm_router.get("/providers/custom-template", response_model=LLMCustomProviderTemplateResponseModel)
async def get_llm_custom_provider_template():
    registry = _load_llm_provider_registry()
    return LLMCustomProviderTemplateResponseModel(
        success=True,
        message=core_i18n.t(
            "llm.providers.custom_template.loaded", fallback="LLM custom provider template loaded"
        ),
        data=LLMCustomProviderTemplateDataModel(
            template=registry.custom_provider,
            defaults=_build_custom_provider_defaults(registry.custom_provider),
        ),
    )


@llm_router.post("/providers/discover-models", response_model=DiscoverLLMModelsApiResponseModel)
async def discover_llm_provider_models(payload: DiscoverLLMModelsRequestModel):
    models = await _discover_openai_compatible_models(
        payload.base_url,
        payload.api_key,
        payload.api_format,
    )
    return DiscoverLLMModelsApiResponseModel(
        success=True,
        message=core_i18n.t(
            "llm.providers.models.discovered", fallback="LLM provider models discovered"
        ),
        data=DiscoverLLMModelsResponseModel(
            models=models, default_model=models[0] if models else None
        ),
    )


@llm_router.post("/providers/test", response_model=TestLLMProviderApiResponseModel)
async def test_llm_provider_connection(payload: TestLLMProviderRequestModel):
    provider_payload = LLMProviderConfigModel.model_validate(payload.provider)
    provider_payload = normalize_masked_llm_provider_secrets(
        payload.provider_id,
        provider_payload,
        get_config(),
    )
    registry = _load_llm_provider_registry()
    registry_meta = find_provider_meta(
        registry,
        str(provider_payload.provider_type or payload.provider_id).strip().lower(),
    )
    effective_meta = (
        resolve_provider_plan_meta(registry_meta, provider_payload.provider_plan)
        if registry_meta is not None
        else None
    )
    chat_service = provider_payload.services.chat
    if (
        not (provider_payload.base_url or "").strip()
        and effective_meta
        and effective_meta.default_base_url
    ):
        provider_payload.base_url = effective_meta.default_base_url
    if not (chat_service.api_key or "").strip() and provider_payload.api_key:
        chat_service.api_key = provider_payload.api_key
    if not (chat_service.base_url or "").strip() and provider_payload.base_url:
        chat_service.base_url = provider_payload.base_url
    try:
        result = await _test_llm_provider_connection(
            payload.provider_id,
            provider_payload,
            payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to test LLM provider connection")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TestLLMProviderApiResponseModel(
        success=True,
        message=core_i18n.t(
            "llm.providers.connection.succeeded", fallback="LLM provider connection succeeded"
        ),
        data=TestLLMProviderResponseModel(**result),
    )
