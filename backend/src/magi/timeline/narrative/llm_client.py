"""DiaryNarrativeLLMClient — wraps L2LLMJsonClientMixin for timeline diary generation."""

from __future__ import annotations

from typing import Iterable, Optional

from ...config.models import LLMScenario
from ...llm import ScenarioLLMPool
from ...memory.l2.llm_json_client import L2LLMJsonClientMixin
from ...core.logger import get_logger
from .output_schema import DiaryNarrativeOutput
from .prompts import (
    DIARY_NARRATIVE_SYSTEM_PROMPT,
    assign_short_ids,
    build_diary_narrative_user_prompt,
)

logger = get_logger("magi.timeline.narrative.llm_client")


class DiaryNarrativeLLMClient(L2LLMJsonClientMixin):
    """Single-shot diary generator.

    Uses the existing L2LLMJsonClientMixin._generate_json helper, which:
      - sends a JSON-mode chat completion via ScenarioLLMPool
      - retries on rate-limit errors (1s/2s/4s backoff)
      - returns {} on adapter unavailability or invalid JSON

    For Plan 2 we don't add a new retry layer — the mixin's behavior is sufficient.
    """

    def __init__(self, *, scenario_llm_pool: Optional[ScenarioLLMPool]) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    async def generate(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        episodes: Iterable[dict],
        place_hints: Iterable[str] = (),
        excerpts_by_episode: dict[str, list[str]] | None = None,
    ) -> DiaryNarrativeOutput:
        """Generate a diary narrative for the given period.

        Returns an empty DiaryNarrativeOutput on adapter unavailability or
        invalid JSON (callers should treat this as "no generation possible
        right now" and either retry later or fall back to existing data).

        ``excerpts_by_episode`` (optional) carries short content snippets from
        L1 events inside each episode's window — page titles, message text,
        window names — so the LLM can ground its prose in what actually
        happened. When absent or empty, the prompt falls back to episode
        metadata only.
        """
        # Rewrite episode ids to short tags (e1, e2, ...) so the LLM doesn't
        # have to copy long UUIDs verbatim — it would otherwise hallucinate
        # plausible-looking but wrong UUIDs and 100% of slices would be
        # rejected by the orchestrator. See assign_short_ids docstring.
        full_episodes = list(episodes)
        short_episodes, short_to_full = assign_short_ids(full_episodes)
        full_to_short = {full: short for short, full in short_to_full.items()}

        # Remap excerpts keys from full id → short id so the prompt matches.
        raw_excerpts = excerpts_by_episode or {}
        short_excerpts = {
            full_to_short[full]: snippets
            for full, snippets in raw_excerpts.items()
            if full in full_to_short
        }

        prompt = build_diary_narrative_user_prompt(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=short_episodes,
            place_hints=list(place_hints),
            excerpts_by_episode=short_excerpts,
        )
        raw = await self._generate_json(
            system_prompt=DIARY_NARRATIVE_SYSTEM_PROMPT,
            prompt=prompt,
            request_kind="timeline_diary_narrative",
            scenario=LLMScenario.TIMELINE_DIARY_NARRATIVE,
        )
        output = DiaryNarrativeOutput.from_raw(raw)

        # Translate slice episode_ids from short tags back to full ids. If a
        # slice references an unknown short id (LLM hallucinated despite the
        # contract), leave it untouched so the orchestrator's existing
        # "unknown episode_id" guard logs and skips it.
        unmapped_count = 0
        for slice_ in output.slices:
            full_id = short_to_full.get(slice_.episode_id)
            if full_id is None:
                unmapped_count += 1
                continue
            slice_.episode_id = full_id
        if unmapped_count:
            logger.warning(
                "Diary LLM returned slices with unknown short ids",
                unmapped=unmapped_count,
                known_short_ids=sorted(short_to_full.keys()),
            )
        return output
