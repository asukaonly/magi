"""Bootstrap dialogue service for first-contact persona conversations.

Manages a short persona-styled dialogue sequence on first interaction with a persona.
Extracts user information and writes it to L2 memory.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from ..config.models import LLMScenario
from ..core.logger import get_logger
from ..core.runtime_bindings import require_scenario_llm_pool
from .growth_memory import GrowthMemoryEngine, MilestoneType
from .loader import BootstrapConfig, PersonalityConfig, PersonalityLoader

logger = get_logger(__name__)


class BootstrapDialogueService:
    """Orchestrates the bootstrap dialogue for a persona's first encounter with a user.

    The bootstrap dialogue is a short (2-4 round) persona-styled conversation that
    happens the very first time a user interacts with a persona. Its purposes:
    1. Introduction — the persona introduces itself in-character
    2. User profiling — gathers basic user info (name, how to be addressed, interests)
    3. Writes extracted info to L2 entity store
    """

    def __init__(
        self,
        *,
        personality_loader: PersonalityLoader,
        growth_engine: GrowthMemoryEngine,
        l2_store: Any = None,
    ) -> None:
        self._personality_loader = personality_loader
        self._growth_engine = growth_engine
        self._l2_store = l2_store

    async def needs_bootstrap(self, persona_name: str) -> bool:
        """Check whether this persona needs a bootstrap dialogue."""
        milestones = await self._growth_engine.get_milestones(
            milestone_type=MilestoneType.BOOTSTRAP_COMPLETED,
        )
        for m in milestones:
            if m.metadata.get("persona_name") == persona_name:
                return False
        return True

    def _ensure_bootstrap_config(self, config: PersonalityConfig) -> BootstrapConfig:
        """Return the bootstrap config, synthesizing one from persona traits if absent."""
        if config.bootstrap is not None:
            return config.bootstrap
        persona = config.persona_entity.basic_profile
        return BootstrapConfig(
            style_instruction=(
                f"Speak as {persona.name} would — match the personality's tone and background. "
                f"Keep it brief and natural for a first meeting."
            ),
            opening_line="",
            extract_targets=["name", "interests"],
            max_rounds=3,
        )

    async def get_opening(self, persona_name: str) -> Optional[str]:
        """Generate a bootstrap opening line via LLM, falling back to static config."""
        config = self._personality_loader.load(persona_name)
        bootstrap = self._ensure_bootstrap_config(config)

        generated = await self._generate_opening_via_llm(config, bootstrap)
        if generated:
            return generated

        # Fallback to static opening_line
        return bootstrap.opening_line or None

    async def _generate_opening_via_llm(
        self, config: PersonalityConfig, bootstrap: BootstrapConfig
    ) -> Optional[str]:
        """Use LLM to generate a natural in-character first greeting."""
        persona = config.persona_entity.basic_profile
        identity = config.persona_entity.core_identity

        system_prompt = (
            f"You are {persona.name}. {identity.inner_narrative}\n\n"
            f"Language style: {identity.language_fingerprint}\n"
        )
        if bootstrap.style_instruction:
            system_prompt += f"Style: {bootstrap.style_instruction}\n"
        system_prompt += (
            "\nGenerate a single opening line for your FIRST meeting with a new user. "
            "Requirements:\n"
            "- Stay fully in character\n"
            "- 1-2 sentences max, natural and conversational\n"
            "- Do NOT ask 'what should I call you' — that's a cliché\n"
            "- Instead, open with something characteristic: a remark, a mood, a question that fits your personality\n"
            "- Never mention you are an AI or assistant\n"
            "- Output ONLY the greeting text, nothing else"
        )

        try:
            pool = require_scenario_llm_pool()
            bridge = pool.get(LLMScenario.CORE)
            result = await bridge.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": "Generate your opening line."}],
                max_tokens=150,
                temperature=0.9,
            )
            text = result.strip().strip('"').strip("'")
            if text:
                return text
        except Exception as exc:
            logger.debug("Bootstrap opening LLM generation failed, using fallback: %s", exc)

        return None

    async def reply(
        self,
        *,
        persona_name: str,
        user_id: str,
        session_id: str,
        user_message: str,
        history: List[Dict[str, str]],
    ) -> str:
        """Generate the next bootstrap assistant reply.

        Args:
            persona_name: The current persona name.
            user_id: The user identifier.
            session_id: The active chat session.
            user_message: The latest user message text.
            history: Previous bootstrap dialogue turns as [{"role": ..., "content": ...}].

        Returns:
            The assistant reply text.
        """
        config = self._personality_loader.load(persona_name)
        bootstrap = self._ensure_bootstrap_config(config)

        max_rounds = bootstrap.max_rounds or 3
        current_round = sum(1 for m in history if m.get("role") == "user") + 1
        is_final_round = current_round >= max_rounds

        system_prompt = self._build_system_prompt(config, bootstrap, current_round, max_rounds, is_final_round)

        messages = list(history) + [{"role": "user", "content": user_message}]

        try:
            pool = require_scenario_llm_pool()
            bridge = pool.get(LLMScenario.CORE)
            response = await bridge.chat(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=800,
                temperature=0.8,
            )
        except Exception as exc:
            logger.error("Bootstrap LLM call failed: %s", exc)
            response = config.cached_phrases.on_init[0] if config.cached_phrases.on_init else "Hi."

        if is_final_round:
            await self._extract_and_persist(
                config=config,
                bootstrap=bootstrap,
                user_id=user_id,
                history=messages + [{"role": "assistant", "content": response}],
            )
            await self._growth_engine.record_milestone(
                milestone_type=MilestoneType.BOOTSTRAP_COMPLETED,
                title=f"bootstrap_completed_{persona_name}",
                description=f"Bootstrap dialogue completed for persona {persona_name}",
                metadata={"persona_name": persona_name, "user_id": user_id, "rounds": current_round},
            )

        return response

    def _build_system_prompt(
        self,
        config: PersonalityConfig,
        bootstrap: BootstrapConfig,
        current_round: int,
        max_rounds: int,
        is_final_round: bool,
    ) -> str:
        """Build the system prompt for a bootstrap round."""
        persona = config.persona_entity.basic_profile
        identity = config.persona_entity.core_identity
        parts: List[str] = []

        parts.append(
            f"You are {persona.name}. {identity.inner_narrative}\n"
            f"This is your FIRST conversation with this user. You don't know them yet."
        )

        if bootstrap.style_instruction:
            parts.append(f"\n## Style\n{bootstrap.style_instruction}")

        parts.append(f"\n## Dialogue Progress\nRound {current_round} of {max_rounds}.")

        if bootstrap.extract_targets:
            targets_str = ", ".join(bootstrap.extract_targets)
            parts.append(
                f"\n## Information Goals\n"
                f"Naturally weave in questions to learn: {targets_str}.\n"
                f"Do NOT ask all at once. Spread across rounds. Be conversational, not interrogative."
            )

        if is_final_round:
            parts.append(
                "\n## Final Round\n"
                "This is the last bootstrap round. Wrap up warmly and transition to normal conversation. "
                "Summarize what you've learned about the user in a natural way (e.g. 'got it, so you're...')."
            )
        else:
            parts.append(
                "\n## Continuation\n"
                "Keep the conversation flowing naturally. Don't rush to extract all info at once."
            )

        parts.append(
            "\n## Constraints\n"
            "- Stay fully in character.\n"
            "- Keep responses concise (2-4 sentences).\n"
            "- Never mention you are an AI, system, or assistant.\n"
            "- Never mention 'bootstrap', 'extraction', or 'profiling'."
        )

        return "\n".join(parts)

    async def _extract_and_persist(
        self,
        *,
        config: PersonalityConfig,
        bootstrap: BootstrapConfig,
        user_id: str,
        history: List[Dict[str, str]],
    ) -> None:
        """Use LLM to extract user info from the bootstrap dialogue and write to L2."""
        if not bootstrap.extract_targets or self._l2_store is None:
            return

        targets_str = ", ".join(bootstrap.extract_targets)
        transcript = "\n".join(
            f"{'User' if m['role'] == 'user' else config.persona_entity.basic_profile.name}: {m['content']}"
            for m in history
        )

        extraction_prompt = (
            "Extract user information from this conversation transcript.\n"
            f"Target fields: {targets_str}\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Return a JSON object with extracted fields. Use null for fields not mentioned. "
            "Example: {\"name\": \"Alice\", \"preferred_address\": \"she/her\", \"interests\": [\"coding\", \"music\"]}\n"
            "Return ONLY the JSON object."
        )

        try:
            pool = require_scenario_llm_pool()
            bridge = pool.get(LLMScenario.CORE)
            raw = await bridge.chat(
                system_prompt="You are an information extraction assistant. Output valid JSON only.",
                messages=[{"role": "user", "content": extraction_prompt}],
                max_tokens=500,
                temperature=0.1,
                json_mode=True,
            )
            extracted = json.loads(raw)
        except Exception as exc:
            logger.warning("Bootstrap extraction failed: %s", exc)
            return

        if not isinstance(extracted, dict):
            return

        now = time.time()
        entity_id = f"user_{user_id}"
        for facet_name, facet_value in extracted.items():
            if facet_value is None:
                continue
            value_str = json.dumps(facet_value, ensure_ascii=False) if not isinstance(facet_value, str) else facet_value
            try:
                await self._l2_store.upsert_entity_facet(
                    entity_id=entity_id,
                    entity_type="person",
                    facet_name=facet_name,
                    facet_value=value_str,
                    evidence_event_ids=[],
                    confidence=0.7,
                    observed_at=now,
                    source_type="bootstrap_dialogue",
                )
            except Exception as exc:
                logger.warning("Failed to persist bootstrap facet %s: %s", facet_name, exc)
