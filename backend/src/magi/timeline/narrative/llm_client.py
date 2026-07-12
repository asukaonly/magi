"""DiaryNarrativeLLMClient — wraps L2LLMJsonClientMixin for timeline diary generation."""

from __future__ import annotations

from typing import Iterable, Optional

from ...config.models import LLMScenario
from ...llm import ScenarioLLMPool
from ...memory.l2.llm_json_client import L2LLMJsonClientMixin, L2LLMJsonError
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

    Uses the shared JSON-mode transport, while keeping timeline's explicit
    empty-output fallback separate from L2 projection failure semantics.
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
        prompt, short_to_full = _build_generation_prompt(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=episodes,
            place_hints=place_hints,
            excerpts_by_episode=excerpts_by_episode,
        )
        try:
            raw = await self._generate_json(
                system_prompt=DIARY_NARRATIVE_SYSTEM_PROMPT,
                prompt=prompt,
                request_kind="timeline_diary_narrative",
                scenario=LLMScenario.TIMELINE_DIARY_NARRATIVE,
            )
        except L2LLMJsonError as exc:
            logger.warning(
                "Timeline diary generation unavailable",
                error_type=type(exc).__name__,
            )
            return DiaryNarrativeOutput()
        output = DiaryNarrativeOutput.from_raw(raw)
        _restore_slice_episode_ids(output, short_to_full)
        return output


def _build_generation_prompt(
    *,
    scale: str,
    period_start: float,
    period_end: float,
    episodes: Iterable[dict],
    place_hints: Iterable[str],
    excerpts_by_episode: dict[str, list[str]] | None,
) -> tuple[str, dict[str, str]]:
    # Short ids (e1, e2, ...) reduce hallucinated UUID-shaped slice ids.
    full_episodes = list(episodes)
    short_episodes, short_to_full = assign_short_ids(full_episodes)
    short_excerpts = _short_excerpts_by_episode(excerpts_by_episode or {}, short_to_full)
    prompt = build_diary_narrative_user_prompt(
        scale=scale,
        period_start=period_start,
        period_end=period_end,
        episodes=short_episodes,
        place_hints=list(place_hints),
        excerpts_by_episode=short_excerpts,
    )
    return prompt, short_to_full


def _short_excerpts_by_episode(
    raw_excerpts: dict[str, list[str]],
    short_to_full: dict[str, str],
) -> dict[str, list[str]]:
    full_to_short = {full: short for short, full in short_to_full.items()}
    return {
        full_to_short[full]: snippets
        for full, snippets in raw_excerpts.items()
        if full in full_to_short
    }


def _restore_slice_episode_ids(
    output: DiaryNarrativeOutput,
    short_to_full: dict[str, str],
) -> None:
    unmapped_count = 0
    for slice_ in output.slices:
        full_id = short_to_full.get(slice_.episode_id)
        if full_id is None:
            unmapped_count += 1
            continue
        slice_.episode_id = full_id
    if not unmapped_count:
        return
    logger.warning(
        "Diary LLM returned slices with unknown short ids",
        unmapped=unmapped_count,
        known_short_ids=sorted(short_to_full.keys()),
    )
