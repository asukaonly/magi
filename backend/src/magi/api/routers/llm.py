"""Dedicated LLM catalog and provider utility APIs."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...config import get_config
from ...config.llm_registry import (
    LLMCustomProviderMetaModel,
    LLMProviderCatalogEntryModel,
    build_provider_catalog,
)
from ...config.models import LLMProviderSettings
from .config import (
    DiscoverLLMModelsApiResponseModel,
    DiscoverLLMModelsRequestModel,
    LLMProviderConfigModel,
    TestLLMProviderApiResponseModel,
    TestLLMProviderRequestModel,
    _discover_openai_compatible_models,
    _load_llm_provider_registry,
    _test_llm_provider_connection,
)


llm_router = APIRouter()


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


def _build_custom_provider_defaults(registry_meta: LLMCustomProviderMetaModel) -> LLMProviderConfigModel:
    return LLMProviderConfigModel(
        enabled=True,
        provider_type="custom",
        display_name=registry_meta.display_name or "",
        api_key="",
        base_url="",
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
        message="LLM provider catalog loaded",
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
        message="LLM provider catalog resolved",
        data=LLMProviderCatalogDataModel(providers=catalog),
    )


@llm_router.get("/providers/custom-template", response_model=LLMCustomProviderTemplateResponseModel)
async def get_llm_custom_provider_template():
    registry = _load_llm_provider_registry()
    return LLMCustomProviderTemplateResponseModel(
        success=True,
        message="LLM custom provider template loaded",
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
        message="LLM provider models discovered",
        data={
            "models": models,
            "default_model": models[0] if models else None,
        },
    )


@llm_router.post("/providers/test", response_model=TestLLMProviderApiResponseModel)
async def test_llm_provider_connection(payload: TestLLMProviderRequestModel):
    result = await _test_llm_provider_connection(
        payload.provider_id,
        payload.provider.model_copy(deep=True),
        payload.model,
    )
    return TestLLMProviderApiResponseModel(
        success=True,
        message="LLM provider connection succeeded",
        data=result,
    )
