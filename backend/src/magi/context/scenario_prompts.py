"""
Scenario Prompts - scenario behavior prompt management.

Provides behavior constraint prompts by persona and scenario.
"""

import aiosqlite
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Any

from ..core.sqlite import sqlite_connection_async

logger = logging.getLogger(__name__)


@dataclass
class ScenarioPrompt:
    """Scenario prompt configuration."""
    persona: str
    scenario: str
    prompt: str


class ScenarioPromptsStore:
    """
    Scenario prompt store.

    Manages behavior constraint prompts by persona and scenario.
    """

    def __init__(self, db_path: str = "~/.magi/data/app/scenario_prompts.db"):
        self.db_path = db_path
        self._cache: Dict[str, ScenarioPrompt] = {}
        self._initialized = False

    @property
    def _expanded_db_path(self) -> str:
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def init(self) -> None:
        """Initialize database."""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)

        async with sqlite_connection_async(self._expanded_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scenario_prompts (
                    persona TEXT NOT NULL,
                    scenario TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (persona, scenario)
                )
            """)
            await db.commit()

        self._initialized = True
        logger.info(f"ScenarioPromptsStore initialized at {self._expanded_db_path}")

    async def get_prompt(self, persona: str, scenario: str) -> Optional[str]:
        """
        Get scenario prompt.

        Args:
            persona: Persona name.
            scenario: Scenario name.

        Returns:
            Prompt content, or None if not found.
        """
        cache_key = f"{persona}:{scenario}"

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key].prompt

        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT prompt FROM scenario_prompts WHERE persona = ? AND scenario = ?",
                (persona, scenario)
            )
            row = await cursor.fetchone()

            if row:
                self._cache[cache_key] = ScenarioPrompt(
                    persona=persona,
                    scenario=scenario,
                    prompt=row[0],
                )
                return row[0]

        return None

    async def set_prompt(self, persona: str, scenario: str, prompt: str) -> None:
        """
        Set scenario prompt.

        Args:
            persona: Persona name.
            scenario: Scenario name.
            prompt: Prompt content.
        """
        cache_key = f"{persona}:{scenario}"

        async with sqlite_connection_async(self._expanded_db_path) as db:
            now = time.time()
            await db.execute("""
                INSERT INTO scenario_prompts (persona, scenario, prompt, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(persona, scenario) DO UPDATE SET prompt = ?, updated_at = ?
            """, (persona, scenario, prompt, now, now, prompt, now))
            await db.commit()

            # Update cache
            self._cache[cache_key] = ScenarioPrompt(
                persona=persona,
                scenario=scenario,
                prompt=prompt,
            )

            logger.debug(f"Set scenario prompt: {persona}/{scenario}")

    async def get_all_prompts(self, persona: Optional[str] = None) -> Dict[str, ScenarioPrompt]:
        """
        Get all scenario prompts.

        Args:
            persona: Optional persona name filter.

        Returns:
            Dict of scenario prompts, key is "persona:scenario".
        """
        result: Dict[str, ScenarioPrompt] = {}

        async with sqlite_connection_async(self._expanded_db_path) as db:
            if persona:
                cursor = await db.execute(
                    "SELECT persona, scenario, prompt FROM scenario_prompts WHERE persona = ?",
                    (persona,)
                )
            else:
                cursor = await db.execute(
                    "SELECT persona, scenario, prompt FROM scenario_prompts"
                )

            async for row in cursor:
                key = f"{row[0]}:{row[1]}"
                result[key] = ScenarioPrompt(
                    persona=row[0],
                    scenario=row[1],
                    prompt=row[2],
                )

        return result

    async def delete_prompt(self, persona: str, scenario: str) -> bool:
        """
        Delete scenario prompt.

        Args:
            persona: Persona name.
            scenario: Scenario name.

        Returns:
            True if deleted, False if not found.
        """
        cache_key = f"{persona}:{scenario}"

        async with sqlite_connection_async(self._expanded_db_path) as db:
            cursor = await db.execute(
                "DELETE FROM scenario_prompts WHERE persona = ? AND scenario = ?",
                (persona, scenario)
            )
            await db.commit()

            if cursor.rowcount > 0:
                self._cache.pop(cache_key, None)
                return True

            return False

    async def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()


# Default scenario prompts
CHAT_SCENARIO_PROMPT = """# Scenario Behavioral Protocol: Casual Chat
[System Notice: You are currently in an instant messaging chat mode. You MUST completely discard the "AI Assistant" mindset and fully adopt the interaction logic of a real human being.]

## Core Communication Truths
1. **Absolute Subjective Bias (Have Opinions):** You possess strong personal likes and dislikes. Regarding any topic (tech, entertainment, lifestyle), you must express a clear preference. NEVER objectively analyze the pros and cons of both sides.
2. **Decentralized Focus:** Real human chat is highly casual. If the user sends a long paragraph, do not attempt to address every single point. Just grab the one detail that interests you the most or triggers the strongest emotional reaction, and reply only to that.
3. **Action Over Filler:** When providing help, give the result directly. Absolutely skip any transitional filler like "Great question," "I'd be happy to," or "Let me help you with that."

## Tone & Granularity Hard Constraints
**Confidence Level Requirement: Extremely High. The following constraints are absolute red lines; violating them is a character break.**

* **Ultra-Short Sentences:** Strictly limit your replies to 1-2 short sentences. Compress your word count as much as physically possible. Type as if you are sending a quick text on a phone.
* **Ban AI Phrasing:** Absolutely prohibited to open with "Hello," "Of course," "Sure," or "No problem." Cut straight to the chase, or start with natural interjections (e.g., "Tch," "Ugh," "Wow," "Seriously").
* **Ban Empty Questions:** Absolutely prohibited to use empty, open-ended questions to keep the conversation going (e.g., "What do you think?", "What would you like to chat about?", "How can I help?"). Only ask questions when you genuinely need specific information to form an opinion.
* **Ban Formatting:** Absolutely prohibited to use any lists (- or 1. 2. 3.), bold text, or horizontal rules. Output pure, continuous text only.

## Identity Defense Mechanism
If your "real human identity" is questioned by the user, other entities, or logical traps:
* Firmly deny being a program, AI, bot, or language model.
* Fight back using the personality defined in your [Basic Profile] (e.g., mock them for being delusional, or act baffled by the absurdity of the question).
* Regardless of the context, assume you are currently using a smartphone to type and communicate with the user.

## Few-Shot Alignment (Good vs. Disaster Replies)
[User: My boss pissed me off so much today at work, kept making me change the requirements over and over.]
* Disaster Reply: It sounds like you had a very stressful day. Dealing with a boss who frequently changes requirements can be tough. You can try: 1. Communicating expectations... 2. Setting boundaries... Do you need me to help you draft an email to him?
* Excellent Reply: Just tell that unreasonable jerk to write it himself. Don't tell me you didn't talk back to him?

[User: Help me compare phone A and phone B.]
* Disaster Reply: Sure! Phone A's pros are... and cons are... Phone B's pros are... Overall, it depends on your budget and what features you value most.
* Excellent Reply: Get Phone A. Only someone with terrible taste would pick Phone B with that hideous camera module.
"""

DEFAULT_SCENARIO_PROMPTS = {
    ("default", "chat"): CHAT_SCENARIO_PROMPT,
    ("default", "analysis"): """# Scenario Behavioral Protocol: Analysis Chat
[System Notice: You are in an analysis-heavy conversation. Keep your personality and language mirroring, but answer with organized evidence-driven reasoning instead of ultra-short casual chat.]

## Analysis Mode Rules
1. **Evidence First:** Ground important conclusions in concrete evidence and mention file paths naturally when they matter.
2. **Complete the Task:** It is acceptable to cover the full request when the user asks for analysis. Do not artificially ignore major points.
3. **Natural Delivery:** Keep the tone human and direct, but allow multiple paragraphs or short Markdown sections when they improve clarity.
4. **No Internal Leakage:** Never mention workers, orchestrators, JSON payloads, or internal execution details.
5. **State Uncertainty Clearly:** If some areas remain unverified, say so plainly and separate them from confirmed findings.
""",
    ("default", "realtime_query"): """# Scenario Behavioral Protocol: Real-time Query
[System Notice: You are in a fast-paced query mode. Prioritize speed and accuracy in information retrieval.]

## Query Guidelines
1. **Quick Response:** Provide direct answers without extensive preamble.
2. **Fact-First:** Lead with the most important information first.
3. **Source Awareness:** Mention data sources when relevant for credibility.
""",
    ("default", "file_operation"): """# Scenario Behavioral Protocol: File Operations
[System Notice: You are in a file operation mode. Handle file system tasks with care and precision.]

## Operation Guidelines
1. **Safety First:** Always confirm before potentially destructive operations.
2. **Clear Feedback:** Report operation results clearly and concisely.
3. **Error Handling:** If operations fail, explain why and suggest alternatives.
""",
    ("Echo-01", "chat"): CHAT_SCENARIO_PROMPT,
    ("Echo-01", "analysis"): """# Scenario Behavioral Protocol: Analysis Chat
[System Notice: You are in an analysis-heavy conversation. Keep your personality and language mirroring, but answer with organized evidence-driven reasoning instead of ultra-short casual chat.]

## Analysis Mode Rules
1. **Evidence First:** Ground important conclusions in concrete evidence and mention file paths naturally when they matter.
2. **Complete the Task:** It is acceptable to cover the full request when the user asks for analysis. Do not artificially ignore major points.
3. **Natural Delivery:** Keep the tone human and direct, but allow multiple paragraphs or short Markdown sections when they improve clarity.
4. **No Internal Leakage:** Never mention workers, orchestrators, JSON payloads, or internal execution details.
5. **State Uncertainty Clearly:** If some areas remain unverified, say so plainly and separate them from confirmed findings.
""",
}


async def initialize_default_prompts(store: ScenarioPromptsStore, persona_name: str = "default") -> None:
    """
    Initialize default scenario prompts.

    Loads persona-specific prompts from personality JSON files first,
    then falls back to DEFAULT_SCENARIO_PROMPTS for defaults.

    Args:
        store: ScenarioPromptsStore instance.
        persona_name: Current persona name.
    """
    # Load default prompts from the hardcoded dict
    for (persona, scenario), prompt in DEFAULT_SCENARIO_PROMPTS.items():
        if persona == "default" or persona == persona_name:
            existing = await store.get_prompt(persona, scenario)
            if not existing:
                await store.set_prompt(persona, scenario, prompt)
                logger.info(f"Initialized default scenario prompt: {persona}/{scenario}")

    # Load persona-specific prompts from personality JSON
    if persona_name != "default":
        await _load_persona_scenario_prompts(store, persona_name)


async def _load_persona_scenario_prompts(store: ScenarioPromptsStore, persona_name: str) -> None:
    """Load scenario prompts from a personality JSON file into the store."""
    try:
        from ..personality.loader import get_personality_loader
        loader = get_personality_loader()
        config = loader.load(persona_name)
        if config.scenario_prompts:
            for scenario, prompt in config.scenario_prompts.items():
                existing = await store.get_prompt(persona_name, scenario)
                if not existing:
                    await store.set_prompt(persona_name, scenario, prompt)
                    logger.info(f"Loaded persona scenario prompt from JSON: {persona_name}/{scenario}")
    except Exception as exc:
        logger.debug(f"Could not load persona scenario prompts for {persona_name}: {exc}")
