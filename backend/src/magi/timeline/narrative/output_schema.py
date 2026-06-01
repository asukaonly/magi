"""Diary narrative LLM output schema.

The LLM returns a JSON object with a period-level essence and a list of
per-episode slices. This module parses raw dicts into typed dataclasses
and silently drops malformed entries (callers receive partial data
rather than crashing on a single bad slice).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class DiarySliceNarrative:
    """One generated narrative for a single L2 episode."""

    episode_id: str
    slice_narrative: str = ""
    slice_sensory_detail: str | None = None


@dataclass(slots=True)
class DiaryNarrativeOutput:
    """The full diary narrative output for a period."""

    essence_prose: str = ""
    narrative_style: str = "default"
    slices: list[DiarySliceNarrative] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DiaryNarrativeOutput":
        if not isinstance(raw, Mapping):
            return cls()

        essence = str(raw.get("essence_prose") or "").strip()
        style = str(raw.get("narrative_style") or "default").strip() or "default"

        slices_raw = raw.get("slices") or []
        if not isinstance(slices_raw, list):
            slices_raw = []

        slices: list[DiarySliceNarrative] = []
        for item in slices_raw:
            if not isinstance(item, Mapping):
                continue
            episode_id = str(item.get("episode_id") or "").strip()
            if not episode_id:
                continue
            narrative = str(item.get("slice_narrative") or "").strip()
            sensory_raw = item.get("slice_sensory_detail")
            if isinstance(sensory_raw, str) and sensory_raw.strip():
                sensory = sensory_raw.strip()
            else:
                sensory = None
            slices.append(
                DiarySliceNarrative(
                    episode_id=episode_id,
                    slice_narrative=narrative,
                    slice_sensory_detail=sensory,
                )
            )
        return cls(essence_prose=essence, narrative_style=style or "default", slices=slices)
