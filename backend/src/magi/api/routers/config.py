"""System configuration API router."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...config.loader import get_config, get_config_file_path, save_config
from ...config.llm_registry import (
    LLMCustomProviderMetaModel,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
    load_llm_provider_registry,
    resolve_llm_profile,
)
from ...config.models import LLMCapabilitiesSettings, LLMLimitsSettings
from ...core.logger import get_logger

logger = get_logger(__name__)
config_router = APIRouter()


class AgentConfigModel(BaseModel):
    name: str = Field(default="magi-agent")
    description: Optional[str] = Field(default="Magi AI Agent Framework")


class LLMConfigModel(BaseModel):
    provider: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    custom_name: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    from_env: bool = Field(default=False)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LoopConfigModel(BaseModel):
    strategy: str = Field(default="continuous")
    interval: float = Field(default=1.0)


class MessageBusConfigModel(BaseModel):
    backend: str = Field(default="sqlite")
    max_size: Optional[int] = Field(default=1000)


class MemoryConfigModel(BaseModel):
    backend: str = Field(default="sqlite")
    path: Optional[str] = Field(default="~/.magi/data/memories")


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


class L1ConfigModel(BaseModel):
    enabled: bool = Field(default=True)


class L2ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    backend: str = Field(default="sqlite_networkx")
    graphRules: Optional[str] = Field(default=None)


class L3ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    deployment: str = Field(default="local")
    backend: str = Field(default="sqlite_vec")
    model: Optional[str] = Field(default=None)
    modelStatus: Optional[str] = Field(default="not_downloaded")


class L4ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    summaryTypes: List[str] = Field(default_factory=lambda: ["user_events"])


class L5ConfigModel(BaseModel):
    enabled: bool = Field(default=True)


class MemoryLayersConfigModel(BaseModel):
    L1: L1ConfigModel = Field(default_factory=L1ConfigModel)
    L2: L2ConfigModel = Field(default_factory=L2ConfigModel)
    L3: L3ConfigModel = Field(default_factory=L3ConfigModel)
    L4: L4ConfigModel = Field(default_factory=L4ConfigModel)
    L5: L5ConfigModel = Field(default_factory=L5ConfigModel)


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
    memory_layers: MemoryLayersConfigModel = Field(default_factory=MemoryLayersConfigModel)


class ConfigResponse(BaseModel):
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


class LLMProviderRegistryResponse(BaseModel):
    success: bool
    message: str
    data: Optional[LLMProviderRegistryModel] = None


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
                icon="sparkles",
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
                icon="brain",
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
                display_name="GLM",
                description="Friendly experience for Chinese-first scenarios",
                icon="zap",
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
        ],
        custom_provider=LLMCustomProviderMetaModel(
            enabled=True,
            display_name="Custom Provider",
            description="Connect OpenAI-compatible or custom format endpoints",
            icon="wand",
            capabilities=LLMCapabilitiesSettings(vision=False, image_output=False, tool_calling=True, reasoning=True, embedding=False),
            fields={
                "custom_name": LLMProviderFieldModel(visible=True, required=True, placeholder="My Provider"),
                "api_format": LLMProviderFieldModel(
                    visible=True, required=True, options=["openai", "anthropic", "custom"]
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


def _build_memory_layers(raw: Dict[str, Any], runtime_config: Any) -> MemoryLayersConfigModel:
    saved_layers = raw.get("memory_layers")
    if isinstance(saved_layers, dict):
        return MemoryLayersConfigModel(**saved_layers)

    memory_cfg = runtime_config.agent.memory
    return MemoryLayersConfigModel(
        L1=L1ConfigModel(enabled=memory_cfg.enable_l1_raw),
        L2=L2ConfigModel(enabled=memory_cfg.enable_l2_relations),
        L3=L3ConfigModel(
            enabled=memory_cfg.enable_l3_embeddings,
            model=memory_cfg.embedding.local_model,
            modelStatus="ready",
        ),
        L4=L4ConfigModel(enabled=memory_cfg.enable_l4_summaries),
        L5=L5ConfigModel(enabled=memory_cfg.enable_l5_capabilities),
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
    from_env: bool = False,
) -> LLMConfigModel:
    api_key = runtime_config.llm.api_key
    llm_api_key = "***" if (mask_api_key and api_key) else api_key
    resolved = resolve_llm_profile(runtime_config.llm, registry)
    return LLMConfigModel(
        provider=str(getattr(runtime_config.llm.provider, "value", runtime_config.llm.provider)),
        model=runtime_config.llm.model,
        api_key=llm_api_key,
        base_url=runtime_config.llm.base_url,
        custom_name=raw_llm.get("custom_name"),
        api_format=raw_llm.get("api_format"),
        from_env=from_env,
        capability_override_enabled=bool(runtime_config.llm.capability_override_enabled),
        capabilities=resolved.capabilities,
        limits=resolved.limits,
        provider_options=resolved.provider_options,
    )


def _build_system_config(mask_api_key: bool = True) -> SystemConfigModel:
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
        memory=MemoryConfigModel(
            backend=raw.get("memory", {}).get("backend", "sqlite"),
            path=runtime_config.agent.memory.db_path,
        ),
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
        memory_layers=_build_memory_layers(raw, runtime_config),
    )


def _build_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    updates: Dict[str, Any] = {
        "agent.name": config.agent.name,
        "agent.description": config.agent.description,
        "llm.provider": config.llm.provider,
        "llm.model": config.llm.model,
        "llm.base_url": config.llm.base_url,
        "llm.custom_name": config.llm.custom_name,
        "llm.api_format": config.llm.api_format,
        "llm.capability_override_enabled": config.llm.capability_override_enabled,
        "llm.capabilities": config.llm.capabilities.model_dump(),
        "llm.limits": config.llm.limits.model_dump(),
        "llm.provider_options": config.llm.provider_options,
        "loop.strategy": config.loop.strategy,
        "loop.interval": config.loop.interval,
        "agent.loop_interval": config.loop.interval,
        "agent.message_bus.backend": config.message_bus.backend,
        "agent.message_bus.max_queue_size": config.message_bus.max_size,
        "memory.backend": config.memory.backend,
        "agent.memory.db_path": config.memory.path,
        "features.enable_websocket": config.websocket.enabled,
        "server.port": config.websocket.port,
        "log_level": config.log.level,
        "log.path": config.log.path,
        "preferences": config.preferences.model_dump(),
        "agent.personality.name": config.personality.persona_entity.basic_profile.name if config.personality.persona_entity.basic_profile.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": True,
        "memory_layers": config.memory_layers.model_dump(),
        "tools.builtIn": config.tools.builtIn.model_dump(),
        "tools.skills": config.tools.skills,
        "tools.weather.enabled": config.tools.builtIn.weather.enabled,
        "tools.weather.default_provider": config.tools.builtIn.weather.provider,
        "tools.web_search.enabled": config.tools.builtIn.webSearch.enabled,
        "tools.web_search.default_provider": config.tools.builtIn.webSearch.provider,
        "tools.web_fetch.enabled": config.tools.builtIn.webFetch.enabled,
        "tools.web_fetch.default_provider": "browser" if config.tools.builtIn.webFetch.usePlaywright else "http",
    }
    # Only update API keys if they are not masked values
    if config.llm.api_key and not _is_masked_api_key(config.llm.api_key):
        updates["llm.api_key"] = config.llm.api_key
        os.environ["LLM_API_KEY"] = config.llm.api_key
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

    # Check for environment variable configuration
    env_provider = os.getenv("LLM_PROVIDER")
    env_model = os.getenv("LLM_MODEL")
    env_api_key = os.getenv("LLM_API_KEY")
    env_base_url = os.getenv("LLM_BASE_URL")

    from_env = bool(env_provider or env_model or env_api_key or env_base_url)

    if from_env:
        # Use environment variables
        if env_provider:
            template.llm.provider = env_provider.lower()
        if env_model:
            template.llm.model = env_model
        if env_api_key:
            template.llm.api_key = _mask_api_key(env_api_key)
        if env_base_url:
            template.llm.base_url = env_base_url
        template.llm = _build_llm_config_model(
            runtime_config=type("RuntimeConfigProxy", (), {"llm": template.llm})(),
            raw_llm={},
            registry=registry,
            mask_api_key=False,
            from_env=True,
        )
    elif registry.providers:
        primary = registry.providers[0]
        template.llm.provider = primary.id
        if primary.default_model:
            template.llm.model = primary.default_model
        if primary.default_base_url:
            template.llm.base_url = primary.default_base_url
        template.llm = _build_llm_config_model(
            runtime_config=type("RuntimeConfigProxy", (), {"llm": template.llm})(),
            raw_llm={},
            registry=registry,
            mask_api_key=False,
            from_env=False,
        )

    template.preferences.onboarding_completed = False
    template.preferences.user_mode = None
    return template


@config_router.get("/", response_model=ConfigResponse)
async def get_config_endpoint():
    return ConfigResponse(success=True, message="Configuration loaded", data=_build_system_config())


@config_router.put("/", response_model=ConfigResponse)
async def update_config(config: SystemConfigModel):
    try:
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save config")
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
    if not config.llm.provider:
        return ConfigResponse(success=False, message="LLM provider is required", data=None)
    if not config.llm.model:
        return ConfigResponse(success=False, message="LLM model is required", data=None)
    return ConfigResponse(success=True, message="Configuration valid", data=config)


@config_router.get("/llm-providers", response_model=LLMProviderRegistryResponse)
async def get_llm_provider_registry():
    return LLMProviderRegistryResponse(
        success=True,
        message="LLM provider registry loaded",
        data=_load_llm_provider_registry(),
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

        # Save the full personality config to user storage and set as current
        if config.personality:
            _save_personality_to_user(config.personality)

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
