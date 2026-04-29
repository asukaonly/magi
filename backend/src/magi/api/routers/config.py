"""System configuration API router."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException

from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from ...config.models import LLMCapabilitiesSettings
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshLLMConfigCommand
from ...core.logger import get_logger
from ...bootstrap import refresh_runtime_llm_config
from ..services.config_onboarding import (
    build_onboarding_template as _build_onboarding_template_service,
    load_quick_mode_default_personality,
    quick_mode_personality_locale_candidates,
    quick_mode_personality_sort_key,
    resolve_personality_language_code,
)
from ..services.config_secrets import (
    is_masked_api_key,
    mask_api_key,
)
from ..services.llm_testing_service import get_llm_provider_registry as _load_llm_provider_registry
from .config_update_paths import (
    apply_llm_registry_defaults as _apply_llm_registry_defaults,
    build_full_update_paths as _build_full_update_paths,
    normalize_masked_config_secrets as _normalize_masked_config_secrets,
    prune_sparse_value as _prune_sparse_value,
    selection_limits_from_registry_limits as _selection_limits_from_registry_limits,
)
from .config_schemas import (
    AgentConfigModel,
    BuiltInToolsConfigModel,
    ConfigResponse,
    CrossEncoderConfigModel,
    EmbeddingConfigModel,
    EmbeddingLocalConfigModel,
    EntitySemanticEdgeConfigModel,
    FullPersonalityConfigModel,
    GraphSpreadingConfigModel,
    LLMConfigModel,
    LLMProviderConfigModel,
    LLMSelectionConfigModel,
    MemoryConfigModel,
    MemoryL0ConfigModel,
    MemoryL1ConfigModel,
    MemoryL2ConfigModel,
    MemoryL3ConfigModel,
    MemoryL4ConfigModel,
    MemoryRerankerConfigModel,
    NetworkProxyConfigModel,
    OnboardingTemplateDataModel,
    OnboardingTemplateResponse,
    PersonalitySettingsModel,
    QueryExpansionConfigModel,
    SystemConfigModel,
    TestTelegramConnectionRequest,
    TestTelegramConnectionResponse,
    TimelineConfigModel,
    ToolsConfigModel,
    UserPreferencesModel,
    WeatherToolConfigModel,
    WebFetchToolConfigModel,
    WebSearchToolConfigModel,
)

logger = get_logger(__name__)
config_router = APIRouter()


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


def _build_memory_config(raw: Dict[str, Any], runtime_config: Any) -> MemoryConfigModel:
    memory_cfg = runtime_config.agent.memory
    return MemoryConfigModel(
        db_path=memory_cfg.db_path,
        retention_days=memory_cfg.retention_days,
        history_behavior=getattr(memory_cfg.history_behavior, "value", str(memory_cfg.history_behavior)),
        embedding=EmbeddingConfigModel(
            mode=getattr(memory_cfg.embedding.mode, "value", str(memory_cfg.embedding.mode)),
            local=EmbeddingLocalConfigModel(
                model_source=getattr(memory_cfg.embedding.local.model_source, "value", str(memory_cfg.embedding.local.model_source)),
                managed_model_id=memory_cfg.embedding.local.managed_model_id,
                model_dir_path=memory_cfg.embedding.local.model_dir_path,
                idle_timeout_seconds=memory_cfg.embedding.local.idle_timeout_seconds,
            ),
        ),
        reranker=MemoryRerankerConfigModel(
            top_k=memory_cfg.reranker.top_k,
            cross_encoder=CrossEncoderConfigModel(
                enabled=memory_cfg.reranker.cross_encoder.enabled,
                managed_model_id=memory_cfg.reranker.cross_encoder.managed_model_id,
            ),
        ),
        query_expansion=QueryExpansionConfigModel(
            enabled=memory_cfg.query_expansion.enabled,
        ),
        graph_spreading=GraphSpreadingConfigModel(
            enabled=memory_cfg.graph_spreading.enabled,
        ),
        entity_semantic_edges=EntitySemanticEdgeConfigModel(
            enabled=memory_cfg.entity_semantic_edges.enabled,
        ),
        l0=MemoryL0ConfigModel(
            enabled=memory_cfg.l0.enabled,
            checkpoint_interval_seconds=memory_cfg.l0.checkpoint_interval_seconds,
        ),
        l1=MemoryL1ConfigModel(
            enabled=memory_cfg.l1.enabled,
            vectors_enabled=memory_cfg.l1.vectors_enabled,
        ),
        l2=MemoryL2ConfigModel(
            enabled=memory_cfg.l2.enabled,
            batch_flush_interval_seconds=memory_cfg.l2.batch_flush_interval_seconds,
            auto_extract_relations=memory_cfg.l2.auto_extract_relations,
            conflict_arbitration_enabled=memory_cfg.l2.conflict_arbitration_enabled,
            conflict_arbitration_min_confidence=memory_cfg.l2.conflict_arbitration_min_confidence,
        ),
        l3=MemoryL3ConfigModel(
            enabled=memory_cfg.l3.enabled,
            vectors_enabled=memory_cfg.l3.vectors_enabled,
            llm_summary_enabled=memory_cfg.l3.llm_summary_enabled,
            temporal_llm_timeout_seconds=memory_cfg.l3.temporal_llm_timeout_seconds,
            temporal_llm_min_event_count=memory_cfg.l3.temporal_llm_min_event_count,
            summary_interval_minutes=memory_cfg.l3.summary_interval_minutes,
        ),
        l4=MemoryL4ConfigModel(
            enabled=memory_cfg.l4.enabled,
            vectors_enabled=memory_cfg.l4.vectors_enabled,
        ),
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
    """Load full personality config from the in-memory cache."""
    from ...personality.active_persona import get_current_personality_config

    try:
        cached = get_current_personality_config()
        if cached is not None:
            return FullPersonalityConfigModel(**cached.to_dict())

        logger.warning("No personality config in cache, using default")
        return FullPersonalityConfigModel()
    except Exception as exc:
        logger.warning("Failed to load personality config, using default: %s", exc)
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
            model_metadata_overrides=dict(getattr(provider, "model_metadata_overrides", {}) or {}),
        )

    selections: Dict[str, LLMSelectionConfigModel] = {}
    for selection_id, selection in getattr(runtime_config.llm, "selections", {}).items():
        if selection_id == "embedding":
            embedding_meta = find_embedding_model_meta(
                registry,
                selection.provider_id,
                selection.model,
            )
            resolved_dimension = resolve_embedding_dimension(
                embedding_meta,
                getattr(selection, "embedding_dimension", None),
            )
            if not bool(selection.capability_override_enabled):
                capabilities = LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=False,
                    reasoning=False,
                    embedding=True,
                )
                provider_options = (
                    dict(embedding_meta.provider_options_example)
                    if embedding_meta is not None
                    else dict(selection.provider_options or {})
                )
            else:
                capabilities = selection.capabilities
                provider_options = dict(selection.provider_options or {})

            selections[selection_id] = LLMSelectionConfigModel(
                provider_id=selection.provider_id,
                model=selection.model,
                embedding_dimension=resolved_dimension,
                capability_override_enabled=bool(selection.capability_override_enabled),
                capabilities=capabilities,
                limits=(
                    _selection_limits_from_registry_limits(embedding_meta.limits)
                    if embedding_meta is not None and not bool(selection.capability_override_enabled)
                    else selection.limits
                ),
                provider_options=provider_options,
            )
            continue

        resolved = resolve_llm_profile(
            selection,
            registry,
            provider_settings=runtime_config.llm.providers.get(selection.provider_id),
        )
        selections[selection_id] = LLMSelectionConfigModel(
            provider_id=selection.provider_id,
            model=selection.model,
            embedding_dimension=getattr(selection, "embedding_dimension", None),
            capability_override_enabled=bool(selection.capability_override_enabled),
            capabilities=resolved.capabilities,
            limits=_selection_limits_from_registry_limits(resolved.limits),
            provider_options=resolved.provider_options,
        )

    return LLMConfigModel(
        providers=providers,
        selections=selections,
        model_runtime_overrides=dict(getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}),
    )


def _build_system_config(mask_api_key: bool = False) -> SystemConfigModel:
    runtime_config = get_config()
    raw = _read_raw_yaml()
    registry = _load_llm_provider_registry()

    preferences_data = raw.get("preferences", {})
    network_data = raw.get("network", {})

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
        memory=_build_memory_config(raw, runtime_config),
        preferences=UserPreferencesModel(**preferences_data),
        network=NetworkProxyConfigModel(**network_data),
        personality=_load_full_personality(),
        personalitySettings=PersonalitySettingsModel(
            state_memory_enabled=bool(getattr(runtime_config.agent.personality, "enable_state_memory", True)),
            state_transition_enabled=bool(getattr(runtime_config.agent.personality, "enable_state_transition", True)),
            deep_persona_enabled=bool(getattr(runtime_config.agent.personality, "enable_deep_persona", True)),
        ).normalized(),
        tools=_build_tools(raw, runtime_config),
        timeline=TimelineConfigModel(
            **(raw.get("timeline", {}) if isinstance(raw.get("timeline"), dict) else {})
        ),
    )


def _build_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    normalized = _normalize_masked_secrets(config)
    target_updates = _build_full_update_paths(normalized)
    current_updates = _build_full_update_paths(_build_system_config(mask_api_key=False))

    return {
        path: value
        for path, value in target_updates.items()
        if current_updates.get(path) != value
    }


def _normalize_masked_secrets(config: SystemConfigModel) -> SystemConfigModel:
    return _normalize_masked_config_secrets(config, get_config())


def _mask_api_key(api_key: str) -> str:
    return mask_api_key(api_key)


async def _enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to reload and refresh its LLM config."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info("Runtime command queue unavailable during LLM refresh notification", reason=reason)
        return

    await queue.enqueue_refresh_llm_config(
        RefreshLLMConfigCommand(
            source="config_api",
            reason=reason,
        )
    )


async def _enqueue_runtime_channels_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to restart channel adapters."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info("Runtime command queue unavailable during channels refresh notification", reason=reason)
        return

    from ...events.contracts import RefreshChannelsCommand

    await queue.enqueue_refresh_channels(
        RefreshChannelsCommand(
            source="config_api",
            reason=reason,
        )
    )


def _is_masked_api_key(api_key: Optional[str]) -> bool:
    return is_masked_api_key(api_key)


def _build_onboarding_template() -> SystemConfigModel:
    return _build_onboarding_template_service()


def _resolve_personality_language_code(language: str) -> str:
    return resolve_personality_language_code(language)


def _quick_mode_personality_locale_candidates(language: str) -> List[str]:
    return quick_mode_personality_locale_candidates(language)


def _quick_mode_personality_sort_key(preset_file: Path, payload: Dict[str, Any]) -> tuple[int, int, str, str]:
    return quick_mode_personality_sort_key(preset_file, payload)


def _load_quick_mode_default_personality(language: str) -> Optional[FullPersonalityConfigModel]:
    return load_quick_mode_default_personality(language)


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
        await _enqueue_runtime_llm_refresh_command(reason="config_updated")
        await _enqueue_runtime_channels_refresh_command(reason="config_updated")
        return ConfigResponse(success=True, message="Configuration updated", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update config")
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


@config_router.get("/onboarding-template", response_model=OnboardingTemplateResponse)
async def get_onboarding_template():
    return OnboardingTemplateResponse(
        success=True,
        message="Onboarding template loaded",
        data=OnboardingTemplateDataModel(
            config=_build_onboarding_template(),
        ),
    )


@config_router.post("/channels/telegram/test", response_model=TestTelegramConnectionResponse)
async def test_telegram_connection(payload: TestTelegramConnectionRequest):
    """Test Telegram bot token + proxy by calling getMe."""
    if not payload.bot_token or payload.bot_token.endswith("****"):
        raise HTTPException(status_code=400, detail="A valid bot token is required")

    try:
        import httpx  # noqa: F401
        from telegram import Bot
        from telegram.request import HTTPXRequest
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-telegram-bot is not installed",
        )

    proxy_url = payload.proxy.strip() or None
    if not proxy_url:
        try:
            cfg = get_config()
            proxy_url = cfg.network.proxy_url()
        except Exception:
            pass

    try:
        request = HTTPXRequest(proxy=proxy_url, connect_timeout=10, read_timeout=10)
        bot = Bot(token=payload.bot_token, request=request)
        async with bot:
            me = await bot.get_me()
        return TestTelegramConnectionResponse(
            success=True,
            message=f"Connected to @{me.username}",
            bot_username=me.username or "",
            bot_id=me.id,
        )
    except Exception as exc:
        return TestTelegramConnectionResponse(
            success=False,
            message=str(exc),
        )


@config_router.post("/onboarding-complete", response_model=ConfigResponse)
async def complete_onboarding(config: SystemConfigModel):
    try:
        if config.preferences.user_mode == "quick":
            quick_mode_personality = _load_quick_mode_default_personality(config.preferences.language)
            if quick_mode_personality is not None:
                config.personality = quick_mode_personality
            else:
                logger.warning(
                    "No quick mode personality preset was found for language '%s'; using submitted personality payload",
                    config.preferences.language,
                )

        config.preferences.onboarding_completed = True
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save onboarding configuration")
        refreshed_config = reload_config()

        # Try to initialize agent runtime if not already initialized
        from ...bootstrap import initialize_agent_runtime
        from ...core.runtime_bindings import require_agent_runtime
        try:
            require_agent_runtime()
            # Already initialized, just refresh LLM config
            refresh_runtime_llm_config(refreshed_config)
        except RuntimeError:
            # Not initialized, try to initialize now
            logger.info("Attempting to initialize agent runtime after onboarding")
            await initialize_agent_runtime()
        await _enqueue_runtime_llm_refresh_command(reason="onboarding_completed")

        # NOTE: persona registry entries are created by the frontend via
        # ``POST /api/personas/seed`` after this call returns to avoid duplicate
        # non-builtin entries that conflict with the seeded builtins.

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
