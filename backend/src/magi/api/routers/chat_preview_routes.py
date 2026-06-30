"""HTTP API for /chat/preview — streams persona preview responses.

Three production wiring concerns are deliberately deferred until the dependency
callables fire on first request:
- ``persona_loader_dep`` resolves a ``(seed_slug, locale)`` pair to a lightweight
  persona-preview prompt. The production implementation reads the bundled preset
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
from fastapi.responses import StreamingResponse

from magi.api.routers.chat_preview_schemas import (
    PreviewMessageRequest,
    PreviewPersonaOverride,
)
from magi.chat_preview import PreviewMessage, PreviewMode, run_preview
from magi.core.logger import get_logger

if TYPE_CHECKING:
    from magi.config.models import LLMSettings

logger = get_logger(__name__)

# Persona preview replies are short; cap output so a chatty model can't run long.
_PREVIEW_MAX_TOKENS = 512
_PREVIEW_LIST_LIMIT = 6
_PREVIEW_EXAMPLE_LIMIT = 4

# The persona loader resolves a (seed_slug, locale) pair to a preview prompt.
PersonaLoaderDep = Callable[[], Callable[[str, str], str]]
# Both LLM deps accept an optional unsaved override (onboarding sends its
# not-yet-persisted config so the preview can run before the user saves).
LLMCallDep = Callable[["Optional[LLMSettings]"], Callable[..., AsyncIterator[str]]]
CoreModelDep = Callable[["Optional[LLMSettings]"], str]


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

        # Resolve the system prompt + core model up front so we can return 400
        # for an unknown seed or a config (override or persisted) with no core
        # model selected — instead of leaking a 500 mid-stream.
        try:
            if request.persona_override is not None:
                system_prompt = _build_override_prompt(request.persona_override)
            else:
                resolve_prompt = persona_loader_dep()
                # Raises ValueError → 400 if the seed is unknown.
                system_prompt = resolve_prompt(request.seed_slug, request.locale)

            core_model = core_model_dep(request.llm_override)
            llm_call = llm_call_dep(request.llm_override)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async def streamer() -> AsyncIterator[bytes]:
            async for chunk in run_preview(
                PreviewMode(seed_slug=request.seed_slug or "", core_model=core_model),
                history=[
                    PreviewMessage(role=t.role, content=t.content)
                    for t in request.history
                ],
                message=PreviewMessage(
                    role=request.message.role, content=request.message.content
                ),
                # The prompt is already resolved; run_preview just needs a
                # zero-cost provider for it.
                load_persona_prompt=lambda _slug: system_prompt,
                invoke_llm=llm_call,
            ):
                yield chunk.encode("utf-8")

        return StreamingResponse(streamer(), media_type="text/plain")

    return router


# ---------------------------------------------------------------------------
# Production dependency wiring
# ---------------------------------------------------------------------------


def _resolve_persona_prompt(seed_slug: str, locale: str) -> str:
    """Load a bundled persona preset and produce a flat preview system prompt.

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

    return _build_seed_preview_prompt(data, seed_slug=seed_slug)


def _build_override_prompt(override: PreviewPersonaOverride) -> str:
    """Build a flat preview system prompt from an inline persona identity.

    Generated onboarding personas currently send only their distilled identity
    fields, so the prompt adds the same preview-scene guardrails used by seed
    personas without inventing unavailable registers or examples.
    """
    return (
        f"You are {override.name}. {override.identity_statement}\n\n"
        f"{_preview_scene_instructions()}\n\n"
        f"Language style: {override.sentence_style}\n"
    )


def _build_seed_preview_prompt(data: dict[str, Any], *, seed_slug: str) -> str:
    name = str(data.get("name") or seed_slug)
    identity_core = data.get("identity_core") if isinstance(data.get("identity_core"), dict) else {}
    idiolect = data.get("idiolect") if isinstance(data.get("idiolect"), dict) else {}
    registers = data.get("registers") if isinstance(data.get("registers"), dict) else {}
    chat_register = (
        registers.get("chat")
        if isinstance(registers.get("chat"), dict)
        else {}
    )

    identity = str(identity_core.get("identity_statement") or "").strip()
    style = str(idiolect.get("sentence_style") or "").strip()
    lines = [
        f"You are {name}. {identity}".strip(),
        "",
        _preview_scene_instructions(),
    ]

    values = _string_list(identity_core.get("values_loved"), limit=3)
    rejected = _string_list(identity_core.get("values_rejected"), limit=3)
    biases = _string_list(identity_core.get("attention_biases"), limit=3)
    if values or rejected or biases:
        lines.extend(["", "Stable persona core:"])
        if values:
            lines.append(f"- Values loved: {'; '.join(values)}")
        if rejected:
            lines.append(f"- Values rejected: {'; '.join(rejected)}")
        if biases:
            lines.append(f"- Attention biases: {'; '.join(biases)}")

    lines.extend(["", f"Language style: {style}"])

    quirks = _string_list(idiolect.get("structural_quirks"), limit=_PREVIEW_LIST_LIMIT)
    avoided = _string_list(idiolect.get("vocab_avoided"), limit=_PREVIEW_LIST_LIMIT)
    if quirks or avoided:
        lines.extend(["", "Voice boundaries:"])
        for quirk in quirks:
            lines.append(f"- {quirk}")
        if avoided:
            lines.append(f"- Avoid these service-like phrases: {'; '.join(avoided)}")

    behavior = str(chat_register.get("behavior") or "").strip()
    description = str(chat_register.get("description") or "").strip()
    if description or behavior:
        lines.extend(["", "Default chat behavior:"])
        if description:
            lines.append(f"- Situation: {description}")
        if behavior:
            lines.append(f"- Behavior: {behavior}")

    quiet_hours = _preview_quiet_hours(data.get("quiet_hours"))
    if quiet_hours:
        lines.extend(["", "Tone-down rules:"])
        lines.extend(quiet_hours)

    examples = _string_list(chat_register.get("examples"), limit=_PREVIEW_EXAMPLE_LIMIT)
    if examples:
        lines.extend(["", "Examples to imitate for voice, length, and restraint:"])
        for example in examples:
            lines.append(example)

    lines.extend(
        [
            "",
            "Reply rule: answer the user's latest message in character. Do not explain this "
            "persona card or describe your own design. Keep ordinary preview replies compact; "
            "only expand when the user asks for analysis or concrete help.",
        ]
    )
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _preview_scene_instructions() -> str:
    return (
        "Persona preview scene: this is a short onboarding test chat. Respond as the persona "
        "in normal conversation, not as a narrator explaining the persona."
    )


def _preview_quiet_hours(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for item in raw[:2]:
        if not isinstance(item, dict):
            continue
        condition = str(item.get("condition") or "").strip()
        clamps = item.get("clamps") if isinstance(item.get("clamps"), dict) else {}
        if not condition and not clamps:
            continue
        line = f"- When {condition}, tone the persona down."
        clamp_parts = [f"{key}: {value}" for key, value in clamps.items()]
        if clamp_parts:
            line = f"{line} Constraints: {'; '.join(clamp_parts)}."
        lines.append(line)
    return lines


def _string_list(raw: Any, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()][:limit]


def _default_persona_loader_dep() -> Callable[[str, str], str]:
    return _resolve_persona_prompt


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
