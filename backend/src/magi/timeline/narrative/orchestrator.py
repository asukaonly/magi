"""DiaryNarrativeOrchestrator — gather period evidence, call LLM, persist results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from ...core.logger import get_logger
from ...memory.l3.models import L3Candidate
from .output_schema import DiaryNarrativeOutput

logger = get_logger("magi.timeline.narrative.orchestrator")


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...
    async def get_episode(self, *, episode_id: str) -> dict | None: ...


class _L3SummaryStoreProtocol(Protocol):
    async def upsert_candidate(
        self, *, candidate: L3Candidate, summary_overrides: dict | None = None,
    ) -> dict: ...


class _DiaryLLMClientProtocol(Protocol):
    async def generate(
        self, *, scale: str, period_start: float, period_end: float,
        episodes: Iterable[dict], place_hints: Iterable[str] = (),
    ) -> DiaryNarrativeOutput: ...


@dataclass(slots=True)
class OrchestratorResult:
    """Summary of what was generated for a single orchestrator run."""

    period_start: float
    period_end: float
    scale: str
    episode_count: int
    essence_prose_chars: int
    slices_written: int


class DiaryNarrativeOrchestrator:
    """End-to-end diary generation for a single period window.

    Flow:
      1. List active L2 episodes that overlap [period_start, period_end].
      2. If none, return without calling LLM.
      3. Call DiaryNarrativeLLMClient.generate(...).
      4. If essence is non-empty, upsert an L3 summary via upsert_candidate(insight_key=...).
      5. For each slice in the output, update the matching L2 episode's narrative fields.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        l3_store: _L3SummaryStoreProtocol,
        llm_client: _DiaryLLMClientProtocol,
    ) -> None:
        self._l2_store = l2_store
        self._l3_store = l3_store
        self._llm_client = llm_client

    async def generate_for_window(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        insight_key: str,
        place_hints: Iterable[str] = (),
    ) -> OrchestratorResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active"],
            time_start=period_start,
            time_end=period_end,
            limit=200,
        )

        if not episodes:
            logger.info(
                "Diary generation skipped: no episodes in window",
                scale=scale,
                period_start=period_start,
                period_end=period_end,
            )
            return OrchestratorResult(
                period_start=period_start,
                period_end=period_end,
                scale=scale,
                episode_count=0,
                essence_prose_chars=0,
                slices_written=0,
            )

        output = await self._llm_client.generate(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=episodes,
            place_hints=place_hints,
        )

        # If the LLM call failed or returned empty content, be a no-op.
        if not output.essence_prose and not output.slices:
            logger.warning(
                "Diary generation produced empty output (LLM unavailable or invalid JSON)",
                scale=scale, period_start=period_start, period_end=period_end,
                episode_count=len(episodes),
            )
            return OrchestratorResult(
                period_start=period_start, period_end=period_end, scale=scale,
                episode_count=len(episodes), essence_prose_chars=0, slices_written=0,
            )

        # Write essence to L3 (only if non-empty)
        if output.essence_prose:
            candidate = L3Candidate(
                summary_type="temporal",
                summary_category=scale,
                content=output.essence_prose,
                source_event_ids=[],
                insight_key=insight_key,
            )
            await self._l3_store.upsert_candidate(
                candidate=candidate,
                summary_overrides={
                    "narrative_style": output.narrative_style or "diary_2p",
                    "essence_prose": output.essence_prose,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )

        # Write each slice to its episode
        slices_written = 0
        valid_episode_ids = {ep["episode_id"] for ep in episodes}
        for slice_ in output.slices:
            if slice_.episode_id not in valid_episode_ids:
                logger.warning(
                    "Diary slice references unknown episode_id; skipping",
                    episode_id=slice_.episode_id,
                )
                continue
            if not slice_.slice_narrative:
                continue
            await self._l2_store.update_episode(
                episode_id=slice_.episode_id,
                slice_narrative=slice_.slice_narrative,
                slice_sensory_detail=slice_.slice_sensory_detail or "",
            )
            slices_written += 1

        return OrchestratorResult(
            period_start=period_start,
            period_end=period_end,
            scale=scale,
            episode_count=len(episodes),
            essence_prose_chars=len(output.essence_prose),
            slices_written=slices_written,
        )
