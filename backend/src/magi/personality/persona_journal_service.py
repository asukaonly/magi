"""Persona journal/reflection service.

Generates periodic persona-perspective reflections on recent interactions
and stores them as growth milestones for injection into system prompt context.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..llm.provider import get_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
from ..utils.diagnostic_logging import full_content_logging_enabled
from .active_persona import resolve_persona_config
from .growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from .loader import PersonalityConfig

logger = get_logger(__name__)


# Two or more avoided phrases in a single reflection is the threshold for
# treating an entry as voice-drifted. A single hit may be coincidental
# ("总的来说" is a natural Chinese discourse marker even for personas that
# normally avoid it); two distinct hits in 3-6 sentences is a strong signal
# that the LLM has slipped out of character.
_VOICE_DRIFT_HIT_THRESHOLD = 2


def _detect_voice_drift(
    text: str,
    config: PersonalityConfig | None,
) -> list[str] | None:
    """Return the list of vocab_avoided phrases that appeared in ``text``,
    or ``None`` when the reflection passes the drift guard.

    The reflection feeds into future system prompts as recent journal
    entries; without this guard the persona's own out-of-character output
    becomes the next call's few-shot anchor, which compounds the drift on
    each subsequent reflection.
    """
    if config is None:
        return None
    idiolect = getattr(config, "idiolect", None)
    if idiolect is None:
        return None
    avoided = [
        phrase
        for phrase in getattr(idiolect, "vocab_avoided", []) or []
        if isinstance(phrase, str) and phrase.strip()
    ]
    if not avoided:
        return None
    hits = [phrase for phrase in avoided if phrase in text]
    if len(hits) < _VOICE_DRIFT_HIT_THRESHOLD:
        return None
    return hits


_REFLECTION_SYSTEM_PROMPT = """\
You are writing an internal journal entry from the perspective of a persona.
The entry should reflect on recent interactions and emotional state.
Write in first person, staying in character. Be introspective but concise.

Requirements:
- Reflect on what happened, how you felt, and what you noticed about the user.
- Note any patterns, growth, or concerns.
- Keep the entry between 3-6 sentences.
- Output ONLY the journal entry text, no titles or formatting."""


def _build_reflection_prompt(
    *,
    config: PersonalityConfig,
    persona_name: str,
    emotional_state: Optional[Dict[str, Any]],
    relationship: Optional[Dict[str, Any]],
    recent_milestones: Optional[List[Dict[str, Any]]],
) -> str:
    context_parts: List[str] = [_persona_context_line(config, persona_name)]
    identity_line = _identity_context_line(config)
    if identity_line:
        context_parts.append(identity_line)
    if emotional_state:
        context_parts.append(_emotional_context_line(emotional_state))
    if relationship:
        context_parts.append(_relationship_context_line(relationship))
    milestone_block = _recent_milestones_block(recent_milestones)
    if milestone_block:
        context_parts.append(milestone_block)
    return "\n\n".join(context_parts) if context_parts else "Reflect on your recent state."


def _persona_context_line(config: PersonalityConfig, persona_name: str) -> str:
    persona_desc = f"You are {config.name or persona_name}"
    if config.description:
        persona_desc += f": {config.description}"
    return f"Persona: {persona_desc}"


def _identity_context_line(config: PersonalityConfig) -> str | None:
    identity_statement = config.identity_core.identity_statement
    if not identity_statement:
        return None
    return f"Identity core: {identity_statement}"


def _emotional_context_line(emotional_state: Dict[str, Any]) -> str:
    mood = emotional_state.get("mood", "neutral")
    energy = emotional_state.get("energy_level", 0.7)
    stress = emotional_state.get("stress_level", 0.2)
    return (
        f"Current emotional state: mood={mood}, "
        f"energy={int(float(energy) * 100)}%, "
        f"stress={int(float(stress) * 100)}%"
    )


def _relationship_context_line(relationship: Dict[str, Any]) -> str:
    trust = relationship.get("trust_level", 0.5)
    total = relationship.get("total_interactions", 0)
    sentiment = relationship.get("sentiment_score", 0.0)
    return (
        f"Relationship with user: trust={float(trust):.2f}, "
        f"interactions={total}, sentiment={float(sentiment):.2f}"
    )


def _recent_milestones_block(
    recent_milestones: Optional[List[Dict[str, Any]]],
) -> str | None:
    milestone_lines = []
    for milestone in (recent_milestones or [])[:5]:
        title = milestone.get("title", "")
        description = milestone.get("description", "")
        if title:
            milestone_lines.append(f"- {title}: {description}" if description else f"- {title}")
    if not milestone_lines:
        return None
    return "Recent events:\n" + "\n".join(milestone_lines)


def _reflection_has_voice_drift(
    reflection_text: str,
    *,
    config: PersonalityConfig,
    persona_name: str,
) -> bool:
    drift = _detect_voice_drift(reflection_text, config)
    if drift is None:
        return False
    if full_content_logging_enabled():
        logger.warning(
            "Journal reflection rejected (voice drift): "
            "persona=%s hits=%s preview=%r",
            persona_name,
            drift,
            reflection_text[:120],
        )
    else:
        logger.warning(
            "Journal reflection rejected (voice drift): "
            "persona=%s hit_count=%d reflection_chars=%d",
            persona_name,
            len(drift),
            len(reflection_text),
        )
    return True


def _reflection_metadata(
    persona_name: str,
    emotional_state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"persona_name": persona_name}
    if emotional_state:
        metadata["emotional_snapshot"] = {
            "mood": emotional_state.get("mood", "neutral"),
            "energy_level": emotional_state.get("energy_level"),
            "stress_level": emotional_state.get("stress_level"),
        }
    return metadata


@dataclass(frozen=True, slots=True)
class JournalEntry:
    """A single persona journal entry."""

    milestone_id: str
    content: str
    timestamp: float
    metadata: Dict[str, Any]


class PersonaJournalService:
    """Generates and stores persona-perspective reflections."""

    def __init__(
        self,
        *,
        growth_engine: GrowthMemoryEngine,
    ) -> None:
        self._growth = growth_engine

    async def generate_reflection(
        self,
        *,
        persona_name: str,
        emotional_state: Optional[Dict[str, Any]] = None,
        relationship: Optional[Dict[str, Any]] = None,
        recent_milestones: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[JournalEntry]:
        """Generate a persona-perspective reflection and store it.

        Args:
            persona_name: Active persona identifier.
            emotional_state: Current emotional state dict (mood, energy, stress).
            relationship: Relationship profile dict for the primary user.
            recent_milestones: Recent milestone dicts to reflect on.

        Returns:
            The stored JournalEntry, or None if generation failed.
        """
        config = await resolve_persona_config(persona_name)
        if config is None:
            logger.warning("Cannot generate reflection: persona '%s' not found", persona_name)
            return None

        reflection_text = await self._call_llm(
            _build_reflection_prompt(
                config=config,
                persona_name=persona_name,
                emotional_state=emotional_state,
                relationship=relationship,
                recent_milestones=recent_milestones,
            )
        )
        if not reflection_text:
            return None

        if _reflection_has_voice_drift(
            reflection_text,
            config=config,
            persona_name=persona_name,
        ):
            return None

        return await self._store_reflection_entry(
            persona_name=persona_name,
            reflection_text=reflection_text,
            emotional_state=emotional_state,
        )

    async def _store_reflection_entry(
        self,
        *,
        persona_name: str,
        reflection_text: str,
        emotional_state: Optional[Dict[str, Any]],
    ) -> JournalEntry:
        metadata = _reflection_metadata(persona_name, emotional_state)
        milestone = await self._growth.record_milestone(
            milestone_type=MilestoneType.JOURNAL_ENTRY,
            title=f"Persona reflection ({persona_name})",
            description=reflection_text,
            metadata=metadata,
        )
        logger.info("Generated persona journal entry for '%s': %s", persona_name, milestone.id)
        return JournalEntry(
            milestone_id=milestone.id,
            content=reflection_text,
            timestamp=milestone.timestamp,
            metadata=metadata,
        )

    async def get_recent_entries(
        self,
        persona_name: str,
        limit: int = 5,
    ) -> List[JournalEntry]:
        """Retrieve recent journal entries for a persona."""
        milestones = await self._growth.get_milestones(
            milestone_type=MilestoneType.JOURNAL_ENTRY,
            limit=limit * 3,  # Over-fetch to filter by persona
        )

        entries: List[JournalEntry] = []
        for m in milestones:
            if isinstance(m, Milestone):
                meta = m.metadata or {}
                if meta.get("persona_name") != persona_name:
                    continue
                entries.append(
                    JournalEntry(
                        milestone_id=m.id,
                        content=m.description,
                        timestamp=m.timestamp,
                        metadata=meta,
                    )
                )
            elif isinstance(m, dict):
                meta = m.get("metadata", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                if meta.get("persona_name") != persona_name:
                    continue
                entries.append(
                    JournalEntry(
                        milestone_id=m.get("id", ""),
                        content=m.get("description", ""),
                        timestamp=m.get("timestamp", 0.0),
                        metadata=meta,
                    )
                )
            if len(entries) >= limit:
                break

        return entries

    async def _call_llm(self, user_prompt: str) -> Optional[str]:
        """Make a lightweight LLM call for reflection generation."""
        try:
            pool = get_scenario_llm_pool()
        except Exception:
            logger.warning("LLM pool unavailable for journal reflection")
            return None

        try:
            adapter = pool.get(LLMScenario.AUXILIARY)
        except (ValueError, KeyError):
            try:
                adapter = pool.get(LLMScenario.CORE)
            except (ValueError, KeyError):
                logger.warning("No LLM scenario available for journal reflection")
                return None

        bridge = LLMProviderBridge(adapter)
        t0 = time.monotonic()
        try:
            raw = await bridge.chat(
                system_prompt=_REFLECTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=400,
                temperature=0.7,
                disable_thinking=True,
                event_context={
                    "request_kind": "personality:journal_reflection",
                    "agent_id": "personality:journal",
                },
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.debug("Journal reflection LLM call completed elapsed_ms=%.1f", elapsed_ms)
            return raw.strip() if raw else None
        except Exception:
            logger.warning("Journal reflection LLM call failed", exc_info=True)
            return None
