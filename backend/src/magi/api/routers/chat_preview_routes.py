"""HTTP API for /chat/preview — returns timed persona preview bubbles.

Three production wiring concerns are deliberately deferred until the dependency
callables fire on first request:
- ``persona_loader_dep`` resolves a ``(seed_slug, locale)`` pair to a complete
  persona config. The production implementation reads the bundled preset
  file at ``personalities/{locale}/{seed_slug}.json`` — the same source the
  onboarding seed-previews list comes from — and raises :class:`ValueError` when
  the seed is unknown so the router can return HTTP 400.
- ``llm_call_dep`` returns a callable that streams text chunks. The production
  implementation adapts the configured ``core`` scenario's
  :meth:`LLMAdapter.chat_stream` into the
  ``(*, system_prompt, messages, model) -> AsyncIterator[str]`` shape.
- ``core_model_dep`` returns the ``core`` scenario's currently-selected model
  id from the live config.

Tests inject their own callables for isolation.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Optional

from fastapi import APIRouter, HTTPException

from magi.api.routers.chat_preview_schemas import (
    PreviewDeliverySegment,
    PreviewMessageRequest,
    PreviewMessageResponse,
)
from magi.agent.response_rhythm import (
    ResponseRhythmPlanner,
    extract_persona_rhythm,
    strip_segmentation_sentinel,
)
from magi.chat_preview import (
    PreviewMessage,
    PreviewMode,
    build_preview_prompt_package,
    run_preview,
)
from magi.config import get_config
from magi.core.logger import get_logger
from magi.personality.loader import PersonalityConfig
from magi.api.services.config_secrets import (
    llm_settings_have_masked_secrets,
    normalize_masked_llm_settings_secrets,
)

if TYPE_CHECKING:
    from magi.config.models import LLMSettings

logger = get_logger(__name__)

# Persona preview replies are short; cap output so a chatty model can't run long.
_PREVIEW_MAX_TOKENS = 512

# The persona loader resolves a (seed_slug, locale) pair to a complete config.
PersonaLoaderDep = Callable[[], Callable[[str, str], PersonalityConfig]]
# Both LLM deps accept an optional unsaved override (onboarding sends its
# not-yet-persisted config so the preview can run before the user saves).
LLMCallDep = Callable[["Optional[LLMSettings]"], Callable[..., AsyncIterator[str]]]
CoreModelDep = Callable[["Optional[LLMSettings]"], str]


def _normalize_llm_override(
    llm_override: "LLMSettings | None",
) -> "LLMSettings | None":
    """Restore backend-owned credentials before resolving a temporary adapter."""
    if llm_override is None or not llm_settings_have_masked_secrets(llm_override):
        return llm_override
    return normalize_masked_llm_settings_secrets(llm_override, get_config())


def build_default_chat_preview_router(
    *,
    persona_loader_dep: PersonaLoaderDep,
    llm_call_dep: LLMCallDep,
    core_model_dep: CoreModelDep,
) -> APIRouter:
    """Construct the router given dependency callables.

    Mount with ``prefix='/api'`` in production (final paths: `/api/chat/preview`)
    or without prefix in tests that POST to `/chat/preview` directly.
    """
    router = APIRouter()

    @router.post("/chat/preview")
    async def chat_preview(request: PreviewMessageRequest) -> PreviewMessageResponse:
        logger.info(
            "chat_preview.request",
            seed_slug=request.seed_slug,
            locale=request.locale,
            persona_override=request.persona_override is not None,
            history_turns=len(request.history),
            has_llm_override=request.llm_override is not None,
        )
        # Exactly one persona source is required.
        if request.persona_override is None and not request.seed_slug:
            raise HTTPException(
                status_code=400,
                detail="either seed_slug or persona_override is required",
            )

        # Resolve the normal first-chat prompt + core model up front so we can return 400
        # for an unknown seed or a config (override or persisted) with no core
        # model selected — instead of leaking a 500 mid-stream.
        try:
            if request.persona_override is not None:
                persona_config = PersonalityConfig.from_dict(
                    request.persona_override.model_dump()
                )
            else:
                resolve_persona = persona_loader_dep()
                # Raises ValueError → 400 if the seed is unknown.
                persona_config = resolve_persona(request.seed_slug, request.locale)

            prompt_package = await build_preview_prompt_package(
                persona_config=persona_config,
                user_message=request.message.content,
            )
            persona_rhythm = extract_persona_rhythm(prompt_package.prompt_context)

            llm_override = _normalize_llm_override(request.llm_override)
            core_model = core_model_dep(llm_override)
            llm_call = llm_call_dep(llm_override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        chunks: list[str] = []
        async for chunk in run_preview(
            PreviewMode(seed_slug=request.seed_slug or "", core_model=core_model),
            history=[
                PreviewMessage(role=t.role, content=t.content)
                for t in request.history
            ],
            message=PreviewMessage(
                role=request.message.role, content=request.message.content
            ),
            system_prompt=prompt_package.system_prompt,
            runtime_world_state=prompt_package.runtime_world_state,
            working_context=prompt_package.working_context,
            invoke_llm=llm_call,
        ):
            chunks.append(chunk)

        delivery = await _build_preview_delivery(
            "".join(chunks),
            persona=persona_rhythm,
        )
        return PreviewMessageResponse(
            segments=[
                PreviewDeliverySegment(content=content, delay_ms=delay_ms)
                for content, delay_ms in delivery
            ]
        )

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


def _resolve_persona_config(seed_slug: str, locale: str) -> PersonalityConfig:
    """Load a complete bundled persona preset for normal prompt assembly.

    Reads ``personalities/{locale}/{seed_slug}.json`` directly — the same file
    the onboarding seed-previews list is built from
    (:func:`magi.personality.persona_seed.list_seed_previews`) — so any slug the
    UI can show is resolvable here, even before the persona registry has been
    seeded (which only happens at the end of onboarding).
    """
    from magi.personality.persona_seed import _seed_dir

    seed_file = _seed_dir(locale) / f"{seed_slug}.json"
    try:
        data = json.loads(seed_file.read_text(encoding="utf-8"))
    except Exception as exc:  # FileNotFoundError, JSON errors, etc.
        raise ValueError(f"unknown seed: {seed_slug}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"unknown seed: {seed_slug}")
    return PersonalityConfig.from_dict(data)


async def _build_preview_delivery(
    response_text: str,
    *,
    persona: Any = None,
) -> list[tuple[str, int]]:
    """Return validated preview bubbles with normal-chat delivery delays."""
    plan = await ResponseRhythmPlanner().plan(
        response_text=response_text,
        persona=persona,
        streamed=False,
    )
    if plan is not None:
        return [(segment.content, segment.delay_ms) for segment in plan.segments]
    visible_text = strip_segmentation_sentinel(response_text)
    return [(visible_text, 0)] if visible_text else []


def _default_persona_loader_dep() -> Callable[[str, str], PersonalityConfig]:
    return _resolve_persona_config


async def _stream_preview_text(
    bridge: Any,
    *,
    system_prompt: str,
    messages: list[dict],
) -> AsyncIterator[str]:
    """Yield only the visible assistant text from a provider-bridge stream.

    Preview chat runs the core model with **thinking disabled**
    (``ThinkingDepth.NONE``) and streaming on, mirroring the design: a quick,
    voice-only reply with no deep reasoning. The bridge separates reasoning
    from visible content, so we forward only ``text_delta`` events (dropping
    ``reasoning_delta`` / ``usage``).
    """
    from magi.config.models import ThinkingDepth

    async for event in bridge.chat_response_stream(
        system_prompt=system_prompt,
        messages=messages,
        max_tokens=_PREVIEW_MAX_TOKENS,
        thinking_depth=ThinkingDepth.NONE,
    ):
        if getattr(event, "kind", None) == "text_delta" and getattr(event, "text", None):
            yield event.text


def _default_llm_call_dep(
    llm_override: "LLMSettings | None" = None,
) -> Callable[..., AsyncIterator[str]]:
    """Return an async callable that streams visible reply text for the preview.

    The shape required by :func:`magi.chat_preview.run_preview` is
    ``(*, system_prompt, messages, model) -> AsyncIterator[str]``.

    The core adapter is resolved *eagerly* from the override (or persisted
    config when ``llm_override`` is ``None``) via
    :func:`magi.llm.draft.resolve_adapter_for_scenario`, then wrapped in a
    :class:`~magi.llm.provider_bridge.LLMProviderBridge` so the call goes through
    the same provider-options path the real chat uses — crucially, this lets us
    pass ``ThinkingDepth.NONE`` to disable reasoning (the raw adapter has no
    thinking control, so reasoning models were running slow). Resolving eagerly
    lets a missing selection/provider surface as a 400 (the caller wraps this in
    ``try/except ValueError``) rather than a 500 mid-stream.
    """
    from magi.config.models import LLMScenario
    from magi.llm.draft import resolve_adapter_for_scenario
    from magi.llm.provider_bridge import LLMProviderBridge

    adapter = resolve_adapter_for_scenario(
        LLMScenario.CORE, llm_settings=llm_override
    )
    bridge = LLMProviderBridge(adapter)

    async def invoke(*, system_prompt: str, messages: list[dict], model: str):
        started = time.monotonic()
        first_token_at: float | None = None
        char_count = 0
        logger.info(
            "chat_preview.invoke.start",
            model=model,
            provider=getattr(adapter, "provider_name", None),
            message_count=len(messages),
            thinking="none",
            streaming=True,
            override=bool(llm_override),
        )
        try:
            async for text in _stream_preview_text(
                bridge, system_prompt=system_prompt, messages=messages
            ):
                if first_token_at is None:
                    first_token_at = time.monotonic()
                    logger.info(
                        "chat_preview.invoke.first_token",
                        ttft_ms=round((first_token_at - started) * 1000),
                    )
                char_count += len(text)
                yield text
        finally:
            logger.info(
                "chat_preview.invoke.done",
                total_ms=round((time.monotonic() - started) * 1000),
                ttft_ms=(
                    round((first_token_at - started) * 1000)
                    if first_token_at is not None
                    else None
                ),
                chars=char_count,
            )

    return invoke


def _default_core_model_dep(llm_override: "LLMSettings | None" = None) -> str:
    """Return the ``core`` scenario's currently-selected model id.

    Reads from the unsaved ``llm_override`` when present (onboarding), else the
    persisted config.
    """
    from magi.config import get_config
    from magi.config.models import LLMScenario

    settings = llm_override or get_config().llm
    selection = settings.selections.get(LLMScenario.CORE.value)
    if selection is None or not str(getattr(selection, "model", "") or "").strip():
        raise ValueError("core LLM scenario has no model selected")
    return str(selection.model).strip()


def _build_production_chat_preview_router() -> APIRouter:
    """Construct the chat preview router wired to live deps."""
    return build_default_chat_preview_router(
        persona_loader_dep=_default_persona_loader_dep,
        llm_call_dep=_default_llm_call_dep,
        core_model_dep=_default_core_model_dep,
    )


# Module-level router used by the public route filter in
# :mod:`magi.api.routes`. Constructed at import time so that
# ``_PUBLIC_ROUTE_METHODS`` can match its registered paths.
chat_preview_router: APIRouter = _build_production_chat_preview_router()


__all__ = [
    "build_default_chat_preview_router",
    "chat_preview_router",
]
