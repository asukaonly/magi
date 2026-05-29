"""HTTP API for /chat/preview — streams persona preview responses.

Two production wiring concerns are deliberately deferred until the dependency
callables fire on first request:
- ``persona_loader_dep`` resolves a seed_slug to a flat system prompt. The
  production implementation reads from :class:`magi.personality.loader.PersonalityLoader`
  and raises :class:`ValueError` when the seed is unknown so the router can
  return HTTP 400.
- ``llm_call_dep`` returns a callable that streams text chunks. The production
  implementation adapts the configured ``core`` scenario's
  :meth:`LLMAdapter.chat_stream` into the
  ``(*, system_prompt, messages, model) -> AsyncIterator[str]`` shape.
- ``core_model_dep`` returns the ``core`` scenario's currently-selected model
  id from the live config.

Tests inject their own callables for isolation.
"""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, AsyncIterator, Callable, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from magi.api.routers.chat_preview_schemas import (
    PreviewMessageRequest,
    PreviewPersonaOverride,
)
from magi.chat_preview import PreviewMessage, PreviewMode, run_preview

if TYPE_CHECKING:
    from magi.config.models import LLMSettings
    from magi.personality.loader import PersonalityLoader

PersonaLoaderDep = Callable[[], Callable[[str], str]]
# Both LLM deps accept an optional unsaved override (onboarding sends its
# not-yet-persisted config so the preview can run before the user saves).
LLMCallDep = Callable[["Optional[LLMSettings]"], Callable[..., AsyncIterator[str]]]
CoreModelDep = Callable[["Optional[LLMSettings]"], str]


# Module-scoped lazily-initialized PersonalityLoader. The loader holds an
# instance-level ``_cache`` dict; sharing a singleton lets that cache survive
# across requests. Mirrors the resolver pattern in
# :mod:`magi.api.routers.availability_routes`.
_PERSONA_LOADER: "PersonalityLoader | None" = None
_PERSONA_LOADER_LOCK = Lock()


def _get_or_create_persona_loader() -> "PersonalityLoader":
    from magi.personality.loader import PersonalityLoader

    global _PERSONA_LOADER
    with _PERSONA_LOADER_LOCK:
        if _PERSONA_LOADER is None:
            _PERSONA_LOADER = PersonalityLoader()
        return _PERSONA_LOADER


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
    async def chat_preview(request: PreviewMessageRequest) -> StreamingResponse:
        # Exactly one persona source is required.
        if request.persona_override is None and not request.seed_slug:
            raise HTTPException(
                status_code=400,
                detail="either seed_slug or persona_override is required",
            )

        # Resolve the persona prompt source + core model up front so we can
        # return 400 for an unknown seed or a config (override or persisted)
        # with no core model selected — instead of leaking a 500 mid-stream.
        try:
            if request.persona_override is not None:
                override_prompt = _build_override_prompt(request.persona_override)

                def load_prompt(_seed_slug: str) -> str:
                    return override_prompt

                seed_slug = ""
            else:
                load_prompt = persona_loader_dep()
                # Validate the seed eagerly (raises ValueError → 400 if unknown).
                load_prompt(request.seed_slug)
                seed_slug = request.seed_slug

            core_model = core_model_dep(request.llm_override)
            llm_call = llm_call_dep(request.llm_override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async def streamer() -> AsyncIterator[bytes]:
            async for chunk in run_preview(
                PreviewMode(seed_slug=seed_slug, core_model=core_model),
                history=[
                    PreviewMessage(role=t.role, content=t.content)
                    for t in request.history
                ],
                message=PreviewMessage(
                    role=request.message.role, content=request.message.content
                ),
                load_persona_prompt=load_prompt,
                invoke_llm=llm_call,
            ):
                yield chunk.encode("utf-8")

        return StreamingResponse(streamer(), media_type="text/plain")

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


def _resolve_persona_prompt(seed_slug: str) -> str:
    """Load a persona seed and produce a flat system prompt for preview chat.

    Mirrors the simple form used by
    :mod:`magi.personality.bootstrap_service` so the preview chat speaks in the
    persona's voice without dragging in registers, layers, or quiet hours.
    """
    loader = _get_or_create_persona_loader()
    try:
        config = loader.load(seed_slug)
    except Exception as exc:  # FileNotFoundError, JSON errors, etc.
        raise ValueError(f"unknown seed: {seed_slug}") from exc

    identity = config.identity_core.identity_statement
    style = config.idiolect.sentence_style
    return (
        f"You are {config.name}. {identity}\n\n"
        f"Language style: {style}\n"
    )


def _build_override_prompt(override: PreviewPersonaOverride) -> str:
    """Build a flat preview system prompt from an inline persona identity.

    Mirrors the format produced by :func:`_resolve_persona_prompt` so an
    onboarding-generated (unsaved) persona previews identically to a seed.
    """
    return (
        f"You are {override.name}. {override.identity_statement}\n\n"
        f"Language style: {override.sentence_style}\n"
    )


def _default_persona_loader_dep() -> Callable[[str], str]:
    return _resolve_persona_prompt


def _default_llm_call_dep(
    llm_override: "LLMSettings | None" = None,
) -> Callable[..., AsyncIterator[str]]:
    """Return an async callable that streams text chunks from the core adapter.

    The shape required by :func:`magi.chat_preview.run_preview` is
    ``(*, system_prompt, messages, model) -> AsyncIterator[str]``. The
    underlying primitive is :meth:`LLMAdapter.chat_stream`; we prepend the
    system prompt as a ``{"role": "system", ...}`` message.

    The core adapter is resolved *eagerly* from the override (or persisted
    config when ``llm_override`` is ``None``) via
    :func:`magi.llm.draft.resolve_adapter_for_scenario`, mirroring how the
    provider test-connection and persona generation paths build a throwaway
    adapter from unsaved settings. Resolving eagerly lets a missing
    selection/provider surface as a 400 (the caller wraps this in
    ``try/except ValueError``) rather than a 500 mid-stream.
    """
    from magi.config.models import LLMScenario
    from magi.llm.draft import resolve_adapter_for_scenario

    adapter = resolve_adapter_for_scenario(
        LLMScenario.CORE, llm_settings=llm_override
    )

    async def invoke(*, system_prompt: str, messages: list[dict], model: str):
        wire_messages: list[dict] = []
        if system_prompt:
            wire_messages.append({"role": "system", "content": system_prompt})
        wire_messages.extend(messages)
        async for chunk in adapter.chat_stream(wire_messages):
            yield chunk

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
