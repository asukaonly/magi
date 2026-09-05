"""System configuration API router."""

from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request

from ... import i18n as core_i18n
from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshLLMConfigCommand
from ...core.logger import get_logger
from ...bootstrap import refresh_runtime_llm_config
from ...config.embedding_coordination import (
    embedding_execution_signature,
    get_embedding_config_update_lock,
    pause_rebuilds_for_embedding_config_change,
)
from ...memory.embedding.vector_admin import (
    build_embedding_config_preflight,
    get_embedding_rebuild_manager as _resolve_embedding_rebuild_manager,
)
from ..services.config_onboarding import (
    build_onboarding_template as _build_onboarding_template_service,
    load_quick_mode_personality,
    quick_mode_personality_locale_candidates,
    quick_mode_personality_seed_slug,
    quick_mode_personality_sort_key,
    read_onboarding_completed,
    resolve_personality_language_code,
)
from ..services.config_secrets import (
    is_masked_api_key,
    mask_system_config_secrets,
)
from ..services.llm_testing_service import get_llm_provider_registry as _load_llm_provider_registry
from .config_update_paths import (
    build_full_update_paths as _build_full_update_paths,
    build_onboarding_update_paths as _build_onboarding_update_paths,
    normalize_masked_config_secrets as _normalize_masked_config_secrets,
)
from .config_response_builders import (
    build_llm_config_model as _build_llm_config_model,
    build_memory_config as _build_memory_config,
    load_full_personality as _load_full_personality,
)
from .config_schemas import (
    AgentConfigModel,
    ConfigResponse,
    DiagnosticsConfigModel,
    FullPersonalityConfigModel,
    LanguagePreferenceUpdateRequest,
    NetworkProxyConfigModel,
    OnboardingConfigUpdateRequest,
    OnboardingStatusDataModel,
    OnboardingStatusResponse,
    OnboardingTemplateDataModel,
    OnboardingTemplateResponse,
    PersonalitySettingsModel,
    SystemConfigModel,
    TestTelegramConnectionRequest,
    TestTelegramConnectionResponse,
    TimelineConfigModel,
    UserPreferencesModel,
)

logger = get_logger(__name__)
config_router = APIRouter()
ONBOARDING_RUNTIME_INIT_RESPONSE_BUDGET_SECONDS = 8.0
ONBOARDING_RUNTIME_REFRESH_RESPONSE_BUDGET_SECONDS = 3.0
_ONBOARDING_WRITE_LOCK = get_embedding_config_update_lock()


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


def _read_onboarding_completed() -> bool:
    return read_onboarding_completed(get_config_file_path())


def _get_onboarding_completed_or_error(request: Request) -> bool:
    try:
        return _read_onboarding_completed()
    except Exception as exc:
        logger.exception("Failed to read persisted onboarding status")
        raise HTTPException(
            status_code=500,
            detail=_t(
                request,
                "config.onboarding.status_read_failed",
                "Failed to read onboarding status",
            ),
        ) from exc


def _ensure_onboarding_incomplete(request: Request) -> None:
    if _get_onboarding_completed_or_error(request):
        raise HTTPException(
            status_code=409,
            detail=_t(
                request,
                "config.onboarding.already_completed",
                "Onboarding has already been completed",
            ),
        )


def _request_language(request: Request) -> str | None:
    return request.headers.get("Accept-Language") or None


def _t(request: Request, key: str, fallback: str, **kwargs: Any) -> str:
    return core_i18n.t(key, language=_request_language(request), fallback=fallback, **kwargs)


def _build_system_config(mask_secrets: bool = True) -> SystemConfigModel:
    runtime_config = get_config()
    raw = _read_raw_yaml()
    registry = _load_llm_provider_registry()

    preferences_data = raw.get("preferences", {})
    network_data = raw.get("network", {})
    diagnostics_data = raw.get("diagnostics", {})

    config = SystemConfigModel(
        agent=AgentConfigModel(
            name=runtime_config.agent.name,
            description=raw.get("agent", {}).get("description", "Magi AI Agent Framework"),
        ),
        llm=_build_llm_config_model(
            runtime_config=runtime_config,
            raw_llm=raw.get("llm", {}) if isinstance(raw.get("llm"), dict) else {},
            registry=registry,
        ),
        memory=_build_memory_config(raw, runtime_config),
        preferences=UserPreferencesModel(**preferences_data),
        network=NetworkProxyConfigModel(**network_data),
        diagnostics=DiagnosticsConfigModel(**diagnostics_data),
        personality=_load_full_personality(),
        personalitySettings=PersonalitySettingsModel(
            state_memory_enabled=bool(
                getattr(runtime_config.agent.personality, "enable_state_memory", True)
            ),
            state_transition_enabled=bool(
                getattr(runtime_config.agent.personality, "enable_state_transition", True)
            ),
            deep_persona_enabled=bool(
                getattr(runtime_config.agent.personality, "enable_deep_persona", True)
            ),
        ).normalized(),
        skills=list(runtime_config.tools.skills),
        timeline=TimelineConfigModel(
            **(raw.get("timeline", {}) if isinstance(raw.get("timeline"), dict) else {})
        ),
    )
    return mask_system_config_secrets(config) if mask_secrets else config


def _build_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    normalized = _normalize_masked_secrets(config)
    target_updates = _build_full_update_paths(normalized)
    current_updates = _build_full_update_paths(_build_system_config(mask_secrets=False))

    return {
        path: value for path, value in target_updates.items() if current_updates.get(path) != value
    }


def _normalize_masked_secrets(config: SystemConfigModel) -> SystemConfigModel:
    return _normalize_masked_config_secrets(config, get_config())


def _embedding_execution_signature(config: Any) -> Dict[str, Any]:
    return embedding_execution_signature(config)


def _get_embedding_rebuild_manager() -> Any:
    return _resolve_embedding_rebuild_manager()


async def _enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to reload and refresh its LLM config."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info(
            "Runtime command queue unavailable during LLM refresh notification", reason=reason
        )
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
        logger.info(
            "Runtime command queue unavailable during channels refresh notification", reason=reason
        )
        return

    from ...events.contracts import RefreshChannelsCommand

    await queue.enqueue_refresh_channels(
        RefreshChannelsCommand(
            source="config_api",
            reason=reason,
        )
    )


def _log_deferred_runtime_task_result(task: asyncio.Task[None], *, operation: str) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Deferred runtime operation was cancelled", operation=operation)
    except Exception:
        logger.exception("Deferred runtime operation failed", operation=operation)


async def _run_with_response_budget(
    coro: Coroutine[Any, Any, None],
    *,
    operation: str,
    timeout_seconds: float,
) -> None:
    task = asyncio.create_task(coro)
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(
            "Runtime operation is still running after configuration update response budget",
            operation=operation,
            timeout_seconds=timeout_seconds,
        )
        task.add_done_callback(
            lambda done: _log_deferred_runtime_task_result(done, operation=operation)
        )
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception:
        logger.exception(
            "Runtime operation failed during configuration update", operation=operation
        )


async def _refresh_or_initialize_runtime_after_config_update(
    refreshed_config: Any,
    *,
    reason: str,
) -> None:
    """Refresh the runtime if it exists, or start it after a valid config save."""
    from ...bootstrap import initialize_agent_runtime
    from ...core.runtime_bindings import require_agent_runtime

    try:
        require_agent_runtime()
        refresh_runtime_llm_config(refreshed_config)
    except RuntimeError:
        logger.info(
            "Attempting to initialize agent runtime after configuration update",
            reason=reason,
        )
        await _run_with_response_budget(
            initialize_agent_runtime(),
            operation=f"initialize_agent_runtime_after_{reason}",
            timeout_seconds=ONBOARDING_RUNTIME_INIT_RESPONSE_BUDGET_SECONDS,
        )

    await _run_with_response_budget(
        _enqueue_runtime_llm_refresh_command(reason=reason),
        operation=f"enqueue_runtime_llm_refresh_after_{reason}",
        timeout_seconds=ONBOARDING_RUNTIME_REFRESH_RESPONSE_BUDGET_SECONDS,
    )


async def _persist_config_update(
    *,
    prepare_update: Callable[[], tuple[Dict[str, Any], Any]],
    reason: str,
    save_error_detail: str,
    before_save: Callable[[], None] | None = None,
) -> Any:
    """Serialize config persistence with any affected vector rebuild."""

    async with _ONBOARDING_WRITE_LOCK:
        if before_save is not None:
            before_save()
        updates, proposed_config = prepare_update()
        async with pause_rebuilds_for_embedding_config_change(
            current_config=get_config(),
            proposed_config=proposed_config,
            manager_factory=_get_embedding_rebuild_manager,
        ):
            if not save_config(updates):
                raise HTTPException(status_code=500, detail=save_error_detail)
            refreshed_config = reload_config()
            await _refresh_or_initialize_runtime_after_config_update(
                refreshed_config,
                reason=reason,
            )
            return refreshed_config


def _is_masked_api_key(api_key: Optional[str]) -> bool:
    return is_masked_api_key(api_key)


def _build_onboarding_template() -> SystemConfigModel:
    return _build_onboarding_template_service()


def _resolve_personality_language_code(language: str) -> str:
    return resolve_personality_language_code(language)


def _quick_mode_personality_locale_candidates(language: str) -> List[str]:
    return quick_mode_personality_locale_candidates(language)


def _quick_mode_personality_sort_key(
    preset_file: Path, payload: Dict[str, Any]
) -> tuple[int, int, str, str]:
    return quick_mode_personality_sort_key(preset_file, payload)


def _quick_mode_personality_seed_slug(language: str, scenario: Optional[str]) -> Optional[str]:
    return quick_mode_personality_seed_slug(_resolve_personality_language_code(language), scenario)


def _load_quick_mode_personality(
    language: str,
    scenario: Optional[str] = None,
) -> Optional[FullPersonalityConfigModel]:
    return load_quick_mode_personality(language, scenario)


@config_router.get("/", response_model=ConfigResponse)
async def get_config_endpoint(request: Request):
    return ConfigResponse(
        success=True,
        message=_t(request, "config.messages.loaded", "Configuration loaded"),
        data=_build_system_config(),
    )


@config_router.put("/", response_model=ConfigResponse)
async def update_config(request: Request, config: SystemConfigModel):
    try:

        def prepare_update() -> tuple[Dict[str, Any], SystemConfigModel]:
            config.preferences.onboarding_completed = _get_onboarding_completed_or_error(request)
            with core_i18n.language_context(_request_language(request)):
                updates = _build_update_paths(config)
                proposed_config = _normalize_masked_secrets(config)
                _build_full_update_paths(proposed_config)
            return updates, proposed_config

        await _persist_config_update(
            prepare_update=prepare_update,
            reason="config_updated",
            save_error_detail=_t(
                request,
                "config.errors.save_failed",
                "Failed to save config",
            ),
        )
        await _enqueue_runtime_channels_refresh_command(reason="config_updated")
        return ConfigResponse(
            success=True,
            message=_t(request, "config.messages.updated", "Configuration updated"),
            data=_build_system_config(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update config")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.put("/preferences/language", response_model=ConfigResponse)
async def update_language_preference(
    request: Request,
    payload: LanguagePreferenceUpdateRequest,
):
    try:
        language = core_i18n.app_language_code(payload.language)
        if not save_config({"preferences.language": language}):
            raise HTTPException(
                status_code=500,
                detail=_t(request, "config.errors.save_failed", "Failed to save config"),
            )
        reload_config()
        return ConfigResponse(
            success=True,
            message=_t(request, "config.messages.updated", "Configuration updated"),
            data=_build_system_config(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update language preference")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.post("/embedding-preflight")
async def embedding_config_preflight(request: Request, config: SystemConfigModel):
    try:
        proposed_config = _normalize_masked_secrets(config)
        data = await build_embedding_config_preflight(
            current_config=get_config(),
            proposed_config=proposed_config,
        )
        return {
            "success": True,
            "message": _t(
                request, "config.messages.embedding_preflight", "Embedding configuration checked"
            ),
            "data": data,
        }
    except Exception as exc:
        logger.exception("Failed to check embedding config preflight")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.get("/template", response_model=ConfigResponse)
async def get_config_template(request: Request):
    return ConfigResponse(
        success=True,
        message=_t(request, "config.messages.template", "Configuration template"),
        data=SystemConfigModel(),
    )


@config_router.post("/test", response_model=ConfigResponse)
async def test_config(request: Request, config: SystemConfigModel):
    core_selection = config.llm.selections.get("core")
    if not core_selection:
        return ConfigResponse(
            success=False,
            message=_t(
                request, "config.validation.llm_selections_required", "LLM selections are required"
            ),
            data=None,
        )
    optional_auxiliary = config.llm.selections.get("auxiliary")
    for selection in (core_selection, optional_auxiliary):
        if selection is None:
            continue
        if bool(selection.provider_id) != bool(selection.model):
            return ConfigResponse(
                success=False,
                message=_t(
                    request,
                    "config.validation.llm_provider_model_together",
                    "LLM provider and model must be set together",
                ),
                data=None,
            )
    return ConfigResponse(
        success=True,
        message=_t(request, "config.messages.valid", "Configuration valid"),
        data=mask_system_config_secrets(config),
    )


@config_router.get("/onboarding-template", response_model=OnboardingTemplateResponse)
async def get_onboarding_template(request: Request):
    _ensure_onboarding_incomplete(request)
    template = _build_onboarding_template()
    template.llm = _build_system_config().llm
    return OnboardingTemplateResponse(
        success=True,
        message=_t(request, "config.onboarding.template_loaded", "Onboarding template loaded"),
        data=OnboardingTemplateDataModel(
            config=template,
        ),
    )


@config_router.get("/onboarding-status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(request: Request):
    completed = _get_onboarding_completed_or_error(request)
    return OnboardingStatusResponse(
        success=True,
        message=_t(request, "config.onboarding.status_loaded", "Onboarding status loaded"),
        data=OnboardingStatusDataModel(completed=completed),
    )


@config_router.put("/onboarding-draft", response_model=ConfigResponse)
async def update_onboarding_draft(
    request: Request,
    payload: OnboardingConfigUpdateRequest,
):
    try:

        def prepare_update() -> tuple[Dict[str, Any], SystemConfigModel]:
            draft = SystemConfigModel(llm=payload.llm)
            draft.preferences.language = payload.language
            with core_i18n.language_context(_request_language(request)):
                normalized = _normalize_masked_secrets(draft)
                updates = _build_onboarding_update_paths(normalized, complete=False)
            proposed_config = _build_system_config(mask_secrets=False).model_copy(
                update={"llm": normalized.llm},
                deep=True,
            )
            return updates, proposed_config

        await _persist_config_update(
            prepare_update=prepare_update,
            reason="onboarding_draft_updated",
            save_error_detail=_t(
                request,
                "config.onboarding.save_failed",
                "Failed to save onboarding configuration",
            ),
            before_save=lambda: _ensure_onboarding_incomplete(request),
        )
        return ConfigResponse(
            success=True,
            message=_t(request, "config.onboarding.draft_saved", "Onboarding draft saved"),
            data=_build_system_config(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update onboarding draft")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.post("/channels/telegram/test", response_model=TestTelegramConnectionResponse)
async def test_telegram_connection(request: Request, payload: TestTelegramConnectionRequest):
    """Test Telegram bot token + proxy by calling getMe."""
    if not payload.bot_token or is_masked_api_key(payload.bot_token):
        raise HTTPException(
            status_code=400,
            detail=_t(
                request, "config.telegram.valid_bot_token_required", "A valid bot token is required"
            ),
        )

    try:
        import httpx  # noqa: F401

        telegram_module = import_module("telegram")
        telegram_request_module = import_module("telegram.request")
        Bot = telegram_module.Bot
        HTTPXRequest = telegram_request_module.HTTPXRequest
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=_t(
                request,
                "config.telegram.dependency_missing",
                "python-telegram-bot is not installed",
            ),
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
            message=_t(
                request,
                "config.telegram.connected",
                "Connected to @{username}",
                username=me.username,
            ),
            bot_username=me.username or "",
            bot_id=me.id,
        )
    except Exception as exc:
        return TestTelegramConnectionResponse(
            success=False,
            message=str(exc),
        )


@config_router.post("/onboarding-complete", response_model=ConfigResponse)
async def complete_onboarding(
    request: Request,
    payload: OnboardingConfigUpdateRequest,
):
    try:

        def prepare_update() -> tuple[Dict[str, Any], SystemConfigModel]:
            config = SystemConfigModel(llm=payload.llm)
            config.preferences.language = payload.language
            with core_i18n.language_context(_request_language(request)):
                normalized = _normalize_masked_secrets(config)
                updates = _build_onboarding_update_paths(normalized, complete=True)
            proposed_config = _build_system_config(mask_secrets=False).model_copy(
                update={"llm": normalized.llm},
                deep=True,
            )
            return updates, proposed_config

        await _persist_config_update(
            prepare_update=prepare_update,
            reason="onboarding_completed",
            save_error_detail=_t(
                request,
                "config.onboarding.save_failed",
                "Failed to save onboarding configuration",
            ),
            before_save=lambda: _ensure_onboarding_incomplete(request),
        )

        # NOTE: persona registry entries are created by the frontend via
        # ``POST /api/personas/seed`` after this call returns to avoid duplicate
        # non-builtin entries that conflict with the seeded builtins.

        return ConfigResponse(
            success=True,
            message=_t(request, "config.onboarding.saved", "Onboarding configuration saved"),
            data=_build_system_config(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
