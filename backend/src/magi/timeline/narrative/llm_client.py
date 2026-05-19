"""DiaryNarrativeLLMClient — wraps L2LLMJsonClientMixin for timeline diary generation."""

from __future__ import annotations

from typing import Iterable, Optional

from ...config.models import LLMScenario
from ...llm import ScenarioLLMPool
from ...memory.l2.llm_json_client import L2LLMJsonClientMixin
from .output_schema import DiaryNarrativeOutput
from .prompts import DIARY_NARRATIVE_SYSTEM_PROMPT, build_diary_narrative_user_prompt


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
        prompt = build_diary_narrative_user_prompt(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=list(episodes),
            place_hints=list(place_hints),
            excerpts_by_episode=excerpts_by_episode or {},
        )
        raw = await self._generate_json(
            system_prompt=DIARY_NARRATIVE_SYSTEM_PROMPT,
            prompt=prompt,
            request_kind="timeline_diary_narrative",
            scenario=LLMScenario.TIMELINE_DIARY_NARRATIVE,
        )
        return DiaryNarrativeOutput.from_raw(raw)
