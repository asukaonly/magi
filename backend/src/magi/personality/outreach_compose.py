"""Compose a short, persona-voiced proactive line (outreach Personifier).

Mirrors persona_journal_service: resolve the active persona, render a
compose-specific system prompt, and call LLMProviderBridge.chat. Always
returns a string — falls back to a deterministic template on any failure
so the delivery pipeline never blocks on the LLM.
"""
from __future__ import annotations

from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..llm.provider import get_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
from .active_persona import get_current_personality_config, resolve_persona_config

logger = get_logger(__name__)

_OUTREACH_MAX_TOKENS = 200

_GROUNDING_GUARD = (
    "You are proactively reaching out to the user about a background task you "
    "ran for them. Speak in your own voice, first person, ONE or two short "
    "sentences. You may ONLY restate/announce the facts given below — do NOT "
    "invent results, numbers, or outcomes beyond them. If it fits your "
    "character, end by offering the obvious next step. Output ONLY the message."
)

_KIND_HINT = {
    "task_completed": "The task finished successfully.",
    "task_failed": "The task failed.",
    "task_cancelled": "The task was cancelled.",
}


def _fallback_template(*, kind: str, title: str, facts: str) -> str:
    facts = (facts or "").strip() or "(no details)"
    if kind == "task_completed":
        return facts
    if kind == "task_failed":
        return f"Background task failed: {facts}"
    if kind == "task_cancelled":
        return f"Background task cancelled: {facts}"
    return facts


async def compose_outreach_line(
    *,
    kind: str,
    title: str,
    facts: str,
    persona_name: str | None = None,
) -> str:
    fallback = _fallback_template(kind=kind, title=title, facts=facts)
    try:
        # persona_name=None means "use the active persona". resolve_persona_config
        # requires a real slug (it returns None for None), so read the active
        # persona's cached config directly — otherwise every outreach line would
        # silently degrade to the un-personified fallback in production.
        if persona_name is None:
            config = get_current_personality_config()
        else:
            config = await resolve_persona_config(persona_name)
    except Exception:
        logger.warning("outreach compose: persona resolve failed", exc_info=True)
        return fallback
    if config is None:
        return fallback

    persona_desc = f"You are {getattr(config, 'name', None) or 'an assistant'}"
    description = getattr(config, "description", None)
    if description:
        persona_desc += f": {description}"
    identity = getattr(getattr(config, "identity_core", None), "identity_statement", "") or ""
    system_prompt = "\n".join(p for p in [persona_desc, identity, _GROUNDING_GUARD] if p)

    user_prompt = (
        f"{_KIND_HINT.get(kind, '')}\n"
        f"Task: {title or '(untitled)'}\n"
        f"Facts: {(facts or '').strip() or '(no details)'}"
    )

    try:
        pool = get_scenario_llm_pool()
        try:
            adapter = pool.get(LLMScenario.AUXILIARY)
        except (ValueError, KeyError):
            adapter = pool.get(LLMScenario.CORE)
        bridge = LLMProviderBridge(adapter)
        raw = await bridge.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=_OUTREACH_MAX_TOKENS,
            temperature=0.7,
            disable_thinking=True,
            event_context={"request_kind": "outreach:compose", "agent_id": "outreach:compose"},
        )
    except Exception:
        logger.warning("outreach compose: LLM call failed; using fallback", exc_info=True)
        return fallback

    text = (raw or "").strip()
    return text or fallback
