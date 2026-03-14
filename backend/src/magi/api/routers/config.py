"""System configuration API router."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..llm_draft import build_adapter_from_provider
from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...config.models import LLMProviderSettings
from ...config.llm_registry import (
    LLMCustomProviderMetaModel,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
    find_provider_meta,
    load_llm_provider_registry,
    resolve_llm_profile,
)
from ...config.models import LLMCapabilitiesSettings, LLMLimitsSettings
from ...core.logger import get_logger
from ...llm import LLMProviderBridge, create_llm_adapter
from ...runtime import refresh_runtime_llm_config

logger = get_logger(__name__)
config_router = APIRouter()


class AgentConfigModel(BaseModel):
    name: str = Field(default="magi-agent")
    description: Optional[str] = Field(default="Magi AI Agent Framework")


class LLMProviderConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider_type: str = Field(default="openai")
    display_name: str = Field(default="OpenAI")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)


class LLMSelectionConfigModel(BaseModel):
    provider_id: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMConfigModel(BaseModel):
    providers: Dict[str, LLMProviderConfigModel] = Field(
        default_factory=lambda: {
            "openai": LLMProviderConfigModel()
        }
    )
    selections: Dict[str, LLMSelectionConfigModel] = Field(
        default_factory=lambda: {
            "context_decider": LLMSelectionConfigModel(),
            "core": LLMSelectionConfigModel(),
        }
    )


class LoopConfigModel(BaseModel):
    strategy: str = Field(default="continuous")
    interval: float = Field(default=1.0)


class MessageBusConfigModel(BaseModel):
    backend: str = Field(default="sqlite")
    max_size: Optional[int] = Field(default=1000)


class MemoryConfigModel(BaseModel):
    backend: str = Field(default="sqlite")
    path: Optional[str] = Field(default="~/.magi/data/memories")
    retention_days: int = Field(default=7, ge=1)
    enable_l0: bool = Field(default=True)
    enable_l1: bool = Field(default=True)
    enable_l2: bool = Field(default=True)
    enable_l3: bool = Field(default=True)
    enable_l4: bool = Field(default=True)
    l0_checkpoint_interval_seconds: int = Field(default=30, ge=1)
    runtime_replay_include_l0_only: bool = Field(default=False)
    enable_t1_importance: bool = Field(default=True)
    enable_l2_llm_extraction: bool = Field(default=True)
    enable_l3_llm_summary: bool = Field(default=True)
    enable_l4_skill_extraction: bool = Field(default=True)


class WebSocketConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    port: Optional[int] = Field(default=8000)


class LogConfigModel(BaseModel):
    level: str = Field(default="INFO")
    path: Optional[str] = Field(default=None)


class UserPreferencesModel(BaseModel):
    onboarding_completed: bool = Field(default=False)
    user_mode: Optional[str] = Field(default=None)
    language: str = Field(default="zh")


# Import full PersonalityConfigModel from personality config module
from .personality_config import PersonalityConfigModel as FullPersonalityConfigModel


class WeatherToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="qweather")
    apiKey: Optional[str] = Field(default=None)
    apiUrl: Optional[str] = Field(default=None)


class WebSearchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="duckduckgo")
    apiKey: Optional[str] = Field(default=None)


class WebFetchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    usePlaywright: bool = Field(default=False)


class BuiltInToolsConfigModel(BaseModel):
    weather: WeatherToolConfigModel = Field(default_factory=WeatherToolConfigModel)
    webSearch: WebSearchToolConfigModel = Field(default_factory=WebSearchToolConfigModel)
    webFetch: WebFetchToolConfigModel = Field(default_factory=WebFetchToolConfigModel)


class ToolsConfigModel(BaseModel):
    builtIn: BuiltInToolsConfigModel = Field(default_factory=BuiltInToolsConfigModel)
    skills: List[str] = Field(default_factory=list)


class TimelineSourceConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    sync_mode: str = Field(default="interval")
    sync_interval_minutes: int = Field(default=15, ge=1)
    default_retention_mode: str = Field(default="analyze_only")
    storage_mode: str = Field(default="managed")
    source_path: Optional[str] = Field(default=None)
    fetch_page_content: bool = Field(default=False)
    edge_whitelist: List[str] = Field(default_factory=list)


class TimelineSourcesConfigModel(BaseModel):
    chat: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="watch",
            sync_interval_minutes=1,
            default_retention_mode="analyze_only",
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH"],
        )
    )
    manual_journal: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="manual",
            sync_interval_minutes=1,
            default_retention_mode="retain_raw",
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO"],
        )
    )
    browser_history: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="interval",
            sync_interval_minutes=30,
            default_retention_mode="analyze_only",
            edge_whitelist=["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
        )
    )
    photo_library: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="interval",
            sync_interval_minutes=60,
            default_retention_mode="retain_raw",
            storage_mode="external_reference",
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )


class TimelineConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    expert_mode_edge_override: bool = Field(default=True)
    sources: TimelineSourcesConfigModel = Field(default_factory=TimelineSourcesConfigModel)


class SystemConfigModel(BaseModel):
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    loop: LoopConfigModel = Field(default_factory=LoopConfigModel)
    message_bus: MessageBusConfigModel = Field(default_factory=MessageBusConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    websocket: WebSocketConfigModel = Field(default_factory=WebSocketConfigModel)
    log: LogConfigModel = Field(default_factory=LogConfigModel)
    preferences: UserPreferencesModel = Field(default_factory=UserPreferencesModel)
    personality: FullPersonalityConfigModel = Field(default_factory=FullPersonalityConfigModel)
    tools: ToolsConfigModel = Field(default_factory=ToolsConfigModel)
    timeline: TimelineConfigModel = Field(default_factory=TimelineConfigModel)


class ConfigResponse(BaseModel):
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


class LLMProviderRegistryResponse(BaseModel):
    success: bool
    message: str
    data: Optional[LLMProviderRegistryModel] = None


class DiscoverLLMModelsRequestModel(BaseModel):
    provider_type: str = Field(default="custom")
    base_url: str
    api_key: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default="openai")


class DiscoverLLMModelsResponseModel(BaseModel):
    models: List[str] = Field(default_factory=list)
    default_model: Optional[str] = Field(default=None)


class DiscoverLLMModelsApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[DiscoverLLMModelsResponseModel] = None


class TestLLMProviderRequestModel(BaseModel):
    provider_id: str = Field(default="openai")
    provider: LLMProviderConfigModel
    model: str = Field(default="")


class TestLLMProviderResponseModel(BaseModel):
    model: str
    latency_ms: int
    preview: str = Field(default="")


class TestLLMProviderApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[TestLLMProviderResponseModel] = None


class OnboardingTemplateDataModel(BaseModel):
    config: SystemConfigModel
    llm_providers: LLMProviderRegistryModel


class OnboardingTemplateResponse(BaseModel):
    success: bool
    message: str
    data: Optional[OnboardingTemplateDataModel] = None


def _read_raw_yaml() -> Dict[str, Any]:
    config_path: Path = get_config_file_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Failed to read raw config file")
        return {}


def _llm_provider_registry_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs" / "llm_providers.yaml"


def _default_llm_provider_registry() -> LLMProviderRegistryModel:
    return LLMProviderRegistryModel(
        providers=[
            LLMProviderMetaModel(
                id="openai",
                display_name="OpenAI",
                description="General purpose, strongest ecosystem",
                icon="openai",
                default_model="gpt-5.2",
                default_base_url="https://api.openai.com/v1",
                models=[
                    LLMModelMetaModel(
                        id="gpt-5",
                        label="gpt-5",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=400000, max_output_tokens=128000),
                    ),
                    LLMModelMetaModel(
                        id="gpt-5.2",
                        label="gpt-5.2",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=400000, max_output_tokens=128000),
                    ),
                    LLMModelMetaModel(
                        id="o3",
                        label="o3",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=200000, max_output_tokens=100000),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="anthropic",
                display_name="Anthropic",
                description="Stable for long context and reasoning-heavy tasks",
                icon="anthropic",
                default_model="claude-sonnet-4-6",
                default_base_url="https://api.anthropic.com/v1",
                models=[
                    LLMModelMetaModel(
                        id="claude-sonnet-4-6",
                        label="Claude Sonnet 4.6",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=200000, max_output_tokens=64000),
                    ),
                    LLMModelMetaModel(
                        id="claude-opus-4-6",
                        label="Claude Opus 4.6",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=200000, max_output_tokens=64000),
                    ),
                    LLMModelMetaModel(
                        id="claude-haiku-4-5",
                        label="Claude Haiku 4.5",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=200000, max_output_tokens=32000),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="glm",
                display_name="Z.ai",
                description="Fast general-purpose models from Z.ai",
                icon="zai",
                default_model="glm-5",
                default_base_url="https://open.bigmodel.cn/api/paas/v4",
                models=[
                    LLMModelMetaModel(
                        id="glm-5",
                        label="GLM-5",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=204800, max_output_tokens=131072),
                        provider_options_example={"thinking": {"type": "disabled"}},
                    ),
                    LLMModelMetaModel(
                        id="glm-4.7",
                        label="GLM-4.7",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=128000, max_output_tokens=65536),
                        provider_options_example={"thinking": {"type": "disabled"}},
                    ),
                    LLMModelMetaModel(
                        id="glm-4.7-flash",
                        label="GLM-4.7 Flash",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=128000, max_output_tokens=32768),
                        provider_options_example={"thinking": {"type": "disabled"}},
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="gemini",
                display_name="Google Gemini",
                description="Multimodal models from Google",
                icon="gemini",
                default_model="gemini-2.5-flash",
                default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                models=[
                    LLMModelMetaModel(
                        id="gemini-2.5-pro",
                        label="Gemini 2.5 Pro",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=1048576, max_output_tokens=65536),
                    ),
                    LLMModelMetaModel(
                        id="gemini-2.5-flash",
                        label="Gemini 2.5 Flash",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=1048576, max_output_tokens=65536),
                    ),
                    LLMModelMetaModel(
                        id="gemini-2.5-flash-lite",
                        label="Gemini 2.5 Flash Lite",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=1048576, max_output_tokens=32768),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="deepseek",
                display_name="DeepSeek",
                description="Reasoning and coding models",
                icon="deepseek",
                default_model="deepseek-chat",
                default_base_url="https://api.deepseek.com",
                models=[
                    LLMModelMetaModel(
                        id="deepseek-chat",
                        label="DeepSeek Chat",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=128000, max_output_tokens=8192),
                    ),
                    LLMModelMetaModel(
                        id="deepseek-reasoner",
                        label="DeepSeek Reasoner",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=128000, max_output_tokens=8192),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="kimi",
                display_name="Kimi",
                description="Long-context models from Moonshot AI",
                icon="kimi",
                default_model="moonshot-v1-32k",
                default_base_url="https://api.moonshot.cn/v1",
                models=[
                    LLMModelMetaModel(
                        id="moonshot-v1-8k",
                        label="Moonshot V1 8K",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=8192, max_output_tokens=8192),
                    ),
                    LLMModelMetaModel(
                        id="moonshot-v1-32k",
                        label="Moonshot V1 32K",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=32768, max_output_tokens=8192),
                    ),
                    LLMModelMetaModel(
                        id="moonshot-v1-128k",
                        label="Moonshot V1 128K",
                        capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=128000, max_output_tokens=8192),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
            LLMProviderMetaModel(
                id="minimax",
                display_name="MiniMax",
                description="Multimodal models from MiniMax",
                icon="minimax",
                default_model="MiniMax-M2.5",
                default_base_url="https://api.minimaxi.com/v1",
                models=[
                    LLMModelMetaModel(
                        id="MiniMax-M2.5",
                        label="MiniMax M2.5",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=1000192, max_output_tokens=8192),
                    ),
                    LLMModelMetaModel(
                        id="MiniMax-M2.5-highspeed",
                        label="MiniMax M2.5 Highspeed",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=1000192, max_output_tokens=8192),
                    ),
                    LLMModelMetaModel(
                        id="MiniMax-M2.1",
                        label="MiniMax M2.1",
                        capabilities=LLMCapabilitiesSettings(vision=True, image_output=False, tool_calling=True, reasoning=True, embedding=False),
                        limits=LLMLimitsSettings(context_window=262144, max_output_tokens=8192),
                    ),
                ],
                fields={
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
        ],
        custom_provider=LLMCustomProviderMetaModel(
            enabled=True,
            display_name="Custom Provider",
            description="Connect OpenAI-compatible or Anthropic-compatible endpoints",
            icon="custom",
            capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
            fields={
                "custom_name": LLMProviderFieldModel(visible=True, required=True, placeholder="My Provider"),
                "api_format": LLMProviderFieldModel(
                    visible=True, required=True, options=["openai", "anthropic"]
                ),
                "model": LLMProviderFieldModel(visible=True, required=True),
                "api_key": LLMProviderFieldModel(visible=True, required=True),
                "base_url": LLMProviderFieldModel(visible=True, required=False),
            },
        ),
    )


def _load_llm_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        _llm_provider_registry_path(),
        fallback=_default_llm_provider_registry(),
    )


def _build_memory_config(raw: Dict[str, Any], runtime_config: Any) -> MemoryConfigModel:
    saved_memory = raw.get("memory", {})
    if not isinstance(saved_memory, dict):
        saved_memory = {}

    memory_cfg = runtime_config.agent.memory
    return MemoryConfigModel(
        backend=saved_memory.get("backend", "sqlite"),
        path=memory_cfg.db_path,
        retention_days=memory_cfg.retention_days,
        enable_l0=memory_cfg.enable_l0,
        enable_l1=memory_cfg.enable_l1,
        enable_l2=memory_cfg.enable_l2,
        enable_l3=memory_cfg.enable_l3,
        enable_l4=memory_cfg.enable_l4,
        l0_checkpoint_interval_seconds=memory_cfg.l0_checkpoint_interval_seconds,
        runtime_replay_include_l0_only=memory_cfg.runtime_replay_include_l0_only,
        enable_t1_importance=memory_cfg.enable_t1_importance,
        enable_l2_llm_extraction=memory_cfg.enable_l2_llm_extraction,
        enable_l3_llm_summary=memory_cfg.enable_l3_llm_summary,
        enable_l4_skill_extraction=memory_cfg.enable_l4_skill_extraction,
    )


def _build_tools(raw: Dict[str, Any], runtime_config: Any) -> ToolsConfigModel:
    tools_raw = raw.get("tools", {}) if isinstance(raw.get("tools"), dict) else {}
    built_in = tools_raw.get("builtIn", {}) if isinstance(tools_raw.get("builtIn"), dict) else {}

    weather_runtime = runtime_config.tools.weather
    web_search_runtime = runtime_config.tools.web_search
    web_fetch_runtime = runtime_config.tools.web_fetch

    weather_provider = built_in.get("weather", {}).get("provider", weather_runtime.default_provider)
    weather_provider_cfg = weather_runtime.providers.get(weather_provider)

    web_search_provider = built_in.get("webSearch", {}).get("provider", web_search_runtime.default_provider)
    web_search_provider_cfg = web_search_runtime.providers.get(web_search_provider)

    use_playwright = built_in.get("webFetch", {}).get(
        "usePlaywright", web_fetch_runtime.default_provider == "browser"
    )

    return ToolsConfigModel(
        builtIn=BuiltInToolsConfigModel(
            weather=WeatherToolConfigModel(
                enabled=weather_runtime.enabled,
                provider=weather_provider,
                apiKey=(weather_provider_cfg.api_key if weather_provider_cfg else None),
                apiUrl=(weather_provider_cfg.base_url if weather_provider_cfg else None),
            ),
            webSearch=WebSearchToolConfigModel(
                enabled=web_search_runtime.enabled,
                provider=web_search_provider,
                apiKey=(web_search_provider_cfg.api_key if web_search_provider_cfg else None),
            ),
            webFetch=WebFetchToolConfigModel(
                enabled=web_fetch_runtime.enabled,
                usePlaywright=bool(use_playwright),
            ),
        ),
        skills=tools_raw.get("skills", []),
    )


def _load_full_personality() -> FullPersonalityConfigModel:
    """Load full personality config from personality file, not from agent.yaml."""
    from ...memory.personality_loader import PersonalityLoader
    from ...utils.runtime import get_runtime_paths

    try:
        runtime_paths = get_runtime_paths()
        loader = PersonalityLoader(str(runtime_paths.personalities_dir))

        # Get current personality name from 'current' file or use default
        current_file = runtime_paths.personalities_dir / "current"
        if current_file.exists():
            personality_name = current_file.read_text().strip()
        else:
            personality_name = "default"

        # Load full personality from file
        personality_obj = loader.load(personality_name)
        return FullPersonalityConfigModel(**personality_obj.to_dict())
    except Exception as exc:
        logger.warning("Failed to load personality from file, using default: %s", exc)
        return FullPersonalityConfigModel()


def _build_llm_config_model(
    *,
    runtime_config: Any,
    raw_llm: Dict[str, Any],
    registry: LLMProviderRegistryModel,
    mask_api_key: bool,
) -> LLMConfigModel:
    providers: Dict[str, LLMProviderConfigModel] = {}
    for provider_id, provider in getattr(runtime_config.llm, "providers", {}).items():
        api_key = provider.api_key
        providers[provider_id] = LLMProviderConfigModel(
            enabled=provider.enabled,
            provider_type=str(getattr(provider.provider_type, "value", provider.provider_type)),
            display_name=provider.display_name,
            api_key=(_mask_api_key(api_key) if (mask_api_key and api_key) else api_key),
            base_url=provider.base_url,
            api_format=provider.api_format,
            custom_models=list(getattr(provider, "custom_models", []) or []),
            custom_default_model=getattr(provider, "custom_default_model", None),
        )

    selections: Dict[str, LLMSelectionConfigModel] = {}
    for selection_id, selection in getattr(runtime_config.llm, "selections", {}).items():
        resolved = resolve_llm_profile(selection, registry)
        selections[selection_id] = LLMSelectionConfigModel(
            provider_id=selection.provider_id,
            model=selection.model,
            capability_override_enabled=bool(selection.capability_override_enabled),
            capabilities=resolved.capabilities,
            limits=resolved.limits,
            provider_options=resolved.provider_options,
        )

    return LLMConfigModel(
        providers=providers,
        selections=selections,
    )


def _build_system_config(mask_api_key: bool = False) -> SystemConfigModel:
    runtime_config = get_config()
    raw = _read_raw_yaml()
    registry = _load_llm_provider_registry()

    preferences_data = raw.get("preferences", {})

    return SystemConfigModel(
        agent=AgentConfigModel(
            name=runtime_config.agent.name,
            description=raw.get("agent", {}).get("description", "Magi AI Agent Framework"),
        ),
        llm=_build_llm_config_model(
            runtime_config=runtime_config,
            raw_llm=raw.get("llm", {}) if isinstance(raw.get("llm"), dict) else {},
            registry=registry,
            mask_api_key=mask_api_key,
        ),
        loop=LoopConfigModel(
            strategy=raw.get("loop", {}).get("strategy", "continuous"),
            interval=float(raw.get("loop", {}).get("interval", runtime_config.agent.loop_interval)),
        ),
        message_bus=MessageBusConfigModel(
            backend=runtime_config.agent.message_bus.backend.value,
            max_size=runtime_config.agent.message_bus.max_queue_size,
        ),
        memory=_build_memory_config(raw, runtime_config),
        websocket=WebSocketConfigModel(
            enabled=runtime_config.features.enable_websocket,
            port=runtime_config.server.port,
        ),
        log=LogConfigModel(
            level=runtime_config.log_level,
            path=raw.get("log", {}).get("path"),
        ),
        preferences=UserPreferencesModel(**preferences_data),
        personality=_load_full_personality(),
        tools=_build_tools(raw, runtime_config),
        timeline=TimelineConfigModel(
            **(raw.get("timeline", {}) if isinstance(raw.get("timeline"), dict) else {})
        ),
    )


def _apply_llm_registry_defaults(config: SystemConfigModel, registry: LLMProviderRegistryModel) -> None:
    for provider_id, provider in config.llm.providers.items():
        provider_meta = find_provider_meta(registry, provider_id)
        if provider_meta is None:
            continue

        provider.provider_type = provider_id
        if not provider.display_name:
            provider.display_name = provider_meta.display_name or provider_id.upper()
        if not (provider.base_url or "").strip():
            provider.base_url = provider_meta.default_base_url

    for selection_id, selection in config.llm.selections.items():
        if not selection.provider_id:
            continue

        provider_meta = find_provider_meta(registry, selection.provider_id)
        if provider_meta is None:
            continue

        if not selection.model:
            selection.model = provider_meta.default_model or (
                provider_meta.models[0].id if provider_meta.models else ""
            )

        if not selection.capability_override_enabled and selection.model:
            resolved = resolve_llm_profile(selection, registry)
            config.llm.selections[selection_id] = LLMSelectionConfigModel(
                provider_id=selection.provider_id,
                model=selection.model,
                capability_override_enabled=False,
                capabilities=resolved.capabilities,
                limits=resolved.limits,
                provider_options=resolved.provider_options,
            )


def _build_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    _apply_llm_registry_defaults(config, _load_llm_provider_registry())

    for selection_id, selection in config.llm.selections.items():
        provider = config.llm.providers.get(selection.provider_id)
        if provider is None:
            raise ValueError(
                f"LLM selection '{selection_id}' references unknown provider '{selection.provider_id}'"
            )
        if not provider.enabled:
            raise ValueError(
                f"LLM selection '{selection_id}' references disabled provider '{selection.provider_id}'"
            )

    llm_providers: Dict[str, Any] = {}
    for provider_id, provider in config.llm.providers.items():
        provider_payload = provider.model_dump()
        if _is_masked_api_key(provider_payload.get("api_key")):
            provider_payload["api_key"] = None
        llm_providers[provider_id] = provider_payload

    updates: Dict[str, Any] = {
        "agent.name": config.agent.name,
        "agent.description": config.agent.description,
        "llm.providers": llm_providers,
        "llm.selections": {
            selection_id: selection.model_dump()
            for selection_id, selection in config.llm.selections.items()
        },
        "loop.strategy": config.loop.strategy,
        "loop.interval": config.loop.interval,
        "agent.loop_interval": config.loop.interval,
        "agent.message_bus.backend": config.message_bus.backend,
        "agent.message_bus.max_queue_size": config.message_bus.max_size,
        "memory.backend": config.memory.backend,
        "agent.memory.db_path": config.memory.path,
        "agent.memory.retention_days": config.memory.retention_days,
        "agent.memory.enable_l0": config.memory.enable_l0,
        "agent.memory.enable_l1": config.memory.enable_l1,
        "agent.memory.enable_l2": config.memory.enable_l2,
        "agent.memory.enable_l3": config.memory.enable_l3,
        "agent.memory.enable_l4": config.memory.enable_l4,
        "agent.memory.l0_checkpoint_interval_seconds": config.memory.l0_checkpoint_interval_seconds,
        "agent.memory.runtime_replay_include_l0_only": config.memory.runtime_replay_include_l0_only,
        "agent.memory.enable_t1_importance": config.memory.enable_t1_importance,
        "agent.memory.enable_l2_llm_extraction": config.memory.enable_l2_llm_extraction,
        "agent.memory.enable_l3_llm_summary": config.memory.enable_l3_llm_summary,
        "agent.memory.enable_l4_skill_extraction": config.memory.enable_l4_skill_extraction,
        "agent.memory.enable_l1_raw": config.memory.enable_l1,
        "agent.memory.enable_l2_relations": config.memory.enable_l2,
        "agent.memory.enable_l3_embeddings": config.memory.enable_l3,
        "agent.memory.enable_l4_summaries": config.memory.enable_l3,
        "agent.memory.enable_l5_capabilities": config.memory.enable_l4,
        "features.enable_websocket": config.websocket.enabled,
        "server.port": config.websocket.port,
        "log_level": config.log.level,
        "log.path": config.log.path,
        "preferences": config.preferences.model_dump(),
        "agent.personality.name": config.personality.persona_entity.basic_profile.name if config.personality.persona_entity.basic_profile.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": True,
        "timeline": config.timeline.model_dump(),
        "tools.builtIn": config.tools.builtIn.model_dump(),
        "tools.skills": config.tools.skills,
        "tools.weather.enabled": config.tools.builtIn.weather.enabled,
        "tools.weather.default_provider": config.tools.builtIn.weather.provider,
        "tools.web_search.enabled": config.tools.builtIn.webSearch.enabled,
        "tools.web_search.default_provider": config.tools.builtIn.webSearch.provider,
        "tools.web_fetch.enabled": config.tools.builtIn.webFetch.enabled,
        "tools.web_fetch.default_provider": "browser" if config.tools.builtIn.webFetch.usePlaywright else "http",
    }
    if config.tools.builtIn.weather.apiKey and not _is_masked_api_key(config.tools.builtIn.weather.apiKey):
        updates[f"tools.weather.providers.{config.tools.builtIn.weather.provider}.api_key"] = config.tools.builtIn.weather.apiKey
    if config.tools.builtIn.weather.apiUrl:
        updates[f"tools.weather.providers.{config.tools.builtIn.weather.provider}.base_url"] = config.tools.builtIn.weather.apiUrl
    if config.tools.builtIn.webSearch.apiKey and not _is_masked_api_key(config.tools.builtIn.webSearch.apiKey):
        updates[f"tools.web_search.providers.{config.tools.builtIn.webSearch.provider}.api_key"] = config.tools.builtIn.webSearch.apiKey
    return updates


def _mask_api_key(api_key: str) -> str:
    """Mask API key, showing only first few characters."""
    if not api_key:
        return ""
    # Show first 6 characters (e.g., "sk-abc") followed by "****"
    visible_chars = 6
    if len(api_key) <= visible_chars:
        return api_key[:3] + "***" if len(api_key) > 3 else "***"
    return api_key[:visible_chars] + "****"


def _is_masked_api_key(api_key: Optional[str]) -> bool:
    """Check if API key is a masked/placeholder value."""
    if not api_key:
        return True
    # Check for common masked patterns
    masked_patterns = ["***", "****", "*****"]
    if api_key in masked_patterns:
        return True
    # Check for partial mask pattern like "sk-abc****"
    if api_key.endswith("****") or api_key.endswith("***"):
        return True
    return False


def _build_onboarding_template() -> SystemConfigModel:
    template = SystemConfigModel()
    registry = _load_llm_provider_registry()

    if registry.providers:
        template.llm.providers = {
            provider.id: LLMProviderConfigModel(
                enabled=False,
                provider_type=provider.id,
                display_name=provider.display_name or provider.id.title(),
                base_url="",
                custom_models=[],
                custom_default_model=None,
            )
            for provider in registry.providers
        }
        for selection_id in ("context_decider", "core"):
            selection = template.llm.selections[selection_id]
            selection.provider_id = ""
            selection.model = ""
            selection.provider_options = {}

    template.preferences.onboarding_completed = False
    template.preferences.user_mode = None
    return template


async def _discover_openai_compatible_models(
    base_url: str,
    api_key: Optional[str],
    api_format: Optional[str],
) -> List[str]:
    if api_format not in (None, "", "openai"):
        raise HTTPException(status_code=400, detail="Unsupported model discovery format")

    endpoint = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint, headers=headers) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Model discovery request failed with status {response.status}")
                payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to discover models: {exc}") from exc

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Model discovery response payload is invalid")

    models: List[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                models.append(model_id)
    return models


@config_router.get("/", response_model=ConfigResponse)
async def get_config_endpoint():
    return ConfigResponse(success=True, message="Configuration loaded", data=_build_system_config())


@config_router.put("/", response_model=ConfigResponse)
async def update_config(config: SystemConfigModel):
    try:
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save config")
        refreshed_config = reload_config()
        refresh_runtime_llm_config(refreshed_config)
        return ConfigResponse(success=True, message="Configuration updated", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update config")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.post("/reset", response_model=ConfigResponse)
async def reset_config():
    try:
        config_path = get_config_file_path()
        if config_path.exists():
            config_path.unlink()
        # Trigger default config regeneration.
        _ = get_config()
        return ConfigResponse(success=True, message="Configuration reset", data=_build_system_config())
    except Exception as exc:
        logger.exception("Failed to reset config")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.get("/template", response_model=ConfigResponse)
async def get_config_template():
    return ConfigResponse(success=True, message="Configuration template", data=SystemConfigModel())


@config_router.post("/test", response_model=ConfigResponse)
async def test_config(config: SystemConfigModel):
    core_selection = config.llm.selections.get("core")
    context_selection = config.llm.selections.get("context_decider")
    if not core_selection or not context_selection:
        return ConfigResponse(success=False, message="LLM selections are required", data=None)
    if not core_selection.provider_id or not core_selection.model:
        return ConfigResponse(success=False, message="LLM provider is required", data=None)
    return ConfigResponse(success=True, message="Configuration valid", data=config)


@config_router.get("/llm-providers", response_model=LLMProviderRegistryResponse)
async def get_llm_provider_registry():
    return LLMProviderRegistryResponse(
        success=True,
        message="LLM provider registry loaded",
        data=_load_llm_provider_registry(),
    )


@config_router.post("/llm/providers/discover-models", response_model=DiscoverLLMModelsApiResponseModel)
async def discover_llm_provider_models(payload: DiscoverLLMModelsRequestModel):
    models = await _discover_openai_compatible_models(
        payload.base_url,
        payload.api_key,
        payload.api_format,
    )
    return DiscoverLLMModelsApiResponseModel(
        success=True,
        message="LLM provider models discovered",
        data=DiscoverLLMModelsResponseModel(
            models=models,
            default_model=models[0] if models else None,
        ),
    )


async def _test_llm_provider_connection(
    provider_id: str,
    provider: LLMProviderConfigModel,
    model: str,
) -> Dict[str, Any]:
    runtime_provider = LLMProviderSettings.model_validate(provider.model_dump())
    registry_meta = find_provider_meta(_load_llm_provider_registry(), provider_id)
    adapter = build_adapter_from_provider(
        runtime_provider,
        model=model,
        default_base_url=registry_meta.default_base_url if registry_meta else None,
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
            "surface": "config_provider_test",
            "provider_id": provider_id,
        },
    )
    return {
        "model": model,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "preview": preview[:120].strip(),
    }


@config_router.post("/llm/providers/test", response_model=TestLLMProviderApiResponseModel)
async def test_llm_provider_connection(payload: TestLLMProviderRequestModel):
    registry_meta = find_provider_meta(_load_llm_provider_registry(), payload.provider_id)
    provider_payload = payload.provider.model_copy(deep=True)
    if not (provider_payload.base_url or "").strip() and registry_meta and registry_meta.default_base_url:
        provider_payload.base_url = registry_meta.default_base_url
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
        message="LLM provider connection succeeded",
        data=TestLLMProviderResponseModel(**result),
    )


@config_router.get("/onboarding-template", response_model=OnboardingTemplateResponse)
async def get_onboarding_template():
    return OnboardingTemplateResponse(
        success=True,
        message="Onboarding template loaded",
        data=OnboardingTemplateDataModel(
            config=_build_onboarding_template(),
            llm_providers=_load_llm_provider_registry(),
        ),
    )


def _copy_personality_preset_to_user(preset_id: str, lang: str = "zh") -> bool:
    """Copy a personality preset to user storage and set as current."""
    import json
    from ...utils.runtime import get_runtime_paths

    try:
        # Load preset from built-in directory
        builtin_dir = Path(__file__).resolve().parents[3] / "personalities" / lang
        preset_file = builtin_dir / f"{preset_id}.json"

        if not preset_file.exists():
            # Try fallback to zh if lang is not found
            if lang != "zh":
                builtin_dir = Path(__file__).resolve().parents[3] / "personalities" / "zh"
                preset_file = builtin_dir / f"{preset_id}.json"

            if not preset_file.exists():
                logger.warning("Personality preset not found: %s", preset_id)
                return False

        # Read preset config
        content = preset_file.read_text(encoding="utf-8")
        preset_config = json.loads(content)

        # Save to user storage
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)
        user_file = runtime_paths.personality_file(preset_id)
        user_file.write_text(json.dumps(preset_config, ensure_ascii=False, indent=2), encoding="utf-8")

        # Set as current personality
        current_file = runtime_paths.personalities_dir / "current"
        current_file.write_text(preset_id)

        logger.info("Copied personality preset '%s' to user storage and set as current", preset_id)
        return True
    except Exception as exc:
        logger.error("Failed to copy personality preset: %s", exc)
        return False


def _save_personality_to_user(personality: FullPersonalityConfigModel) -> bool:
    """Save personality config to user storage and set as current."""
    import json
    from ...utils.runtime import get_runtime_paths

    try:
        # Get personality name from basic_profile
        name = personality.persona_entity.basic_profile.name
        if not name:
            name = "user_personality"

        # Sanitize name for filename
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
        safe_name = (safe_name[:50] or "user_personality").strip("_") or "user_personality"

        # Save to user storage
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)
        user_file = runtime_paths.personality_file(safe_name)
        user_file.write_text(
            json.dumps(personality.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Set as current personality
        current_file = runtime_paths.personalities_dir / "current"
        current_file.write_text(safe_name)

        logger.info("Saved personality '%s' to user storage and set as current", safe_name)
        return True
    except Exception as exc:
        logger.error("Failed to save personality to user: %s", exc)
        return False


@config_router.post("/onboarding-complete", response_model=ConfigResponse)
async def complete_onboarding(config: SystemConfigModel):
    try:
        config.preferences.onboarding_completed = True
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save onboarding configuration")
        refreshed_config = reload_config()
        refresh_runtime_llm_config(refreshed_config)

        # Save the full personality config to user storage and set as current
        if config.personality:
            _save_personality_to_user(config.personality)

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
