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
from ..core.runtime_bindings import require_scenario_llm_pool
from ..llm.provider_bridge import LLMProviderBridge
from .active_persona import resolve_persona_config
from .growth_memory import GrowthMemoryEngine, Milestone, MilestoneType
from .loader import PersonalityConfig

logger = get_logger(__name__)


_REFLECTION_SYSTEM_PROMPT = """\
You are writing an internal journal entry from the perspective of a persona.
The entry should reflect on recent interactions and emotional state.
Write in first person, staying in character. Be introspective but concise.

Requirements:
- Reflect on what happened, how you felt, and what you noticed about the user.
- Note any patterns, growth, or concerns.
- Keep the entry between 3-6 sentences.
- Output ONLY the journal entry text, no titles or formatting."""


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

        persona_entity = config.persona_entity
        persona_desc = ""
        if persona_entity and hasattr(persona_entity, "basic_profile"):
            bp = persona_entity.basic_profile
            name = getattr(bp, "name", persona_name)
            occupation = getattr(bp, "occupation", "")
            persona_desc = f"You are {name}"
            if occupation:
                persona_desc += f", {occupation}"

        context_parts: List[str] = []
        if persona_desc:
            context_parts.append(f"Persona: {persona_desc}")

        if emotional_state:
            mood = emotional_state.get("mood", "neutral")
            energy = emotional_state.get("energy_level", 0.7)
            stress = emotional_state.get("stress_level", 0.2)
            context_parts.append(
                f"Current emotional state: mood={mood}, "
                f"energy={int(float(energy) * 100)}%, "
                f"stress={int(float(stress) * 100)}%"
            )

        if relationship:
            trust = relationship.get("trust_level", 0.5)
            total = relationship.get("total_interactions", 0)
            sentiment = relationship.get("sentiment_score", 0.0)
            context_parts.append(
                f"Relationship with user: trust={float(trust):.2f}, "
                f"interactions={total}, sentiment={float(sentiment):.2f}"
            )

        if recent_milestones:
            milestone_lines = []
            for m in recent_milestones[:5]:
                title = m.get("title", "")
                desc = m.get("description", "")
                if title:
                    milestone_lines.append(f"- {title}: {desc}" if desc else f"- {title}")
            if milestone_lines:
                context_parts.append("Recent events:\n" + "\n".join(milestone_lines))

        user_prompt = "\n\n".join(context_parts) if context_parts else "Reflect on your recent state."

        # Generate reflection via LLM
        reflection_text = await self._call_llm(user_prompt)
        if not reflection_text:
            return None

        # Store as milestone
        metadata = {
            "persona_name": persona_name,
        }
        if emotional_state:
            metadata["emotional_snapshot"] = {
                "mood": emotional_state.get("mood", "neutral"),
                "energy_level": emotional_state.get("energy_level"),
                "stress_level": emotional_state.get("stress_level"),
            }

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
                entries.append(JournalEntry(
                    milestone_id=m.id,
                    content=m.description,
                    timestamp=m.timestamp,
                    metadata=meta,
                ))
            elif isinstance(m, dict):
                meta = m.get("metadata", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError):
                        meta = {}
                if meta.get("persona_name") != persona_name:
                    continue
                entries.append(JournalEntry(
                    milestone_id=m.get("id", ""),
                    content=m.get("description", ""),
                    timestamp=m.get("timestamp", 0.0),
                    metadata=meta,
                ))
            if len(entries) >= limit:
                break

        return entries

    async def _call_llm(self, user_prompt: str) -> Optional[str]:
        """Make a lightweight LLM call for reflection generation."""
        try:
            pool = require_scenario_llm_pool()
        except Exception:
            logger.warning("LLM pool unavailable for journal reflection")
            return None

        try:
            adapter = pool.get(LLMScenario.CONTEXT_DECIDER)
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
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.debug("Journal reflection LLM call completed elapsed_ms=%.1f", elapsed_ms)
            return raw.strip() if raw else None
        except Exception:
            logger.warning("Journal reflection LLM call failed", exc_info=True)
            return None
