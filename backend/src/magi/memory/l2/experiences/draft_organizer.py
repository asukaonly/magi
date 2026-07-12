"""Evidence-grounded organization for user-requested experience drafts."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from ...hybrid_retrieval.intent_time import parse_time_range
from .seed_selection_llm import ExperienceSeedSelectionLLMService


_TIME_ISLAND_GAP_SECONDS = 14 * 24 * 60 * 60


def _summary_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _partial_summary_payload(value)
    return decoded if isinstance(decoded, dict) else {}


def _partial_summary_payload(value: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for key in ("label", "title", "content", "summary", "description", "recap"):
        match = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*")', value)
        if not match:
            continue
        try:
            decoded = json.loads(match.group(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(decoded, str) and decoded.strip():
            payload[key] = decoded.strip()
    return payload


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _episode_display_text(episode: Mapping[str, Any]) -> tuple[str, str]:
    summary_value = episode.get("summary")
    payload = _summary_payload(summary_value)
    title = _first_text(
        episode.get("user_label"),
        payload.get("label"),
        payload.get("title"),
        episode.get("label"),
    )
    summary = _first_text(
        episode.get("user_note"),
        payload.get("content"),
        payload.get("summary"),
        payload.get("description"),
        payload.get("recap"),
        "" if payload else summary_value,
    )
    if ":" in title and not _first_text(payload.get("label"), payload.get("title")):
        title = title.split(":", 1)[1].strip(" .-_/").replace("-", " ").replace("_", " ")
    return title, summary


def _event_time(event: Mapping[str, Any]) -> float:
    return float(event.get("timestamp") or event.get("created_at") or 0.0)


def _time_islands(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = sorted((event for event in events if _event_time(event) > 0), key=_event_time)
    islands: list[list[dict[str, Any]]] = []
    for event in ordered:
        if not islands or _event_time(event) - _event_time(islands[-1][-1]) > _TIME_ISLAND_GAP_SECONDS:
            islands.append([event])
        else:
            islands[-1].append(event)
    return islands


def _ambiguous_choices(islands: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        {
            "choice_id": f"period-{index + 1}",
            "time_start": _event_time(island[0]),
            "time_end": _event_time(island[-1]),
            "event_count": len(island),
            "preview": str(island[0].get("content") or "").strip()[:160],
        }
        for index, island in enumerate(islands)
    ]


def _episode_preview(episode: Mapping[str, Any]) -> dict[str, Any]:
    title, summary = _episode_display_text(episode)
    return {
        "ref_type": "episode",
        "ref_id": str(episode.get("episode_id") or ""),
        "title": title,
        "summary": summary,
        "time_start": episode.get("time_start"),
        "time_end": episode.get("time_end"),
        "event_count": max(0, int(episode.get("source_event_count") or 0)),
    }


def _chapter_from_episode(episode: Mapping[str, Any], *, position: int) -> dict[str, Any]:
    title, summary = _episode_display_text(episode)
    return {
        "chapter_id": f"chapter-{position + 1}-{uuid.uuid4().hex[:8]}",
        "title": title or f"Chapter {position + 1}",
        "summary": summary,
        "time_start": episode.get("time_start"),
        "time_end": episode.get("time_end"),
        "episode_ids": [str(episode["episode_id"])],
        "event_ids": [],
        "event_count": max(0, int(episode.get("source_event_count") or 0)),
    }


async def _anchor_episodes(l2: Any, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            continue
        episode = await l2.find_episode_for_event(event_id=event_id)
        if episode is None or str(episode.get("status") or "active") != "active":
            continue
        by_id[str(episode["episode_id"])] = episode
    return sorted(by_id.values(), key=lambda item: float(item.get("time_start") or 0.0))


async def organize_experience_draft(
    unified_memory: Any,
    *,
    query_text: str,
    time_start: float | None = None,
    time_end: float | None = None,
    selector: Any | None = None,
) -> dict[str, Any]:
    """Retrieve real evidence and persist an editable experience draft."""
    query = str(query_text or "").strip()
    if not query:
        raise ValueError("Experience description is required")
    if time_start is None and time_end is None:
        parsed = parse_time_range(query, None)
        time_start = parsed.start if parsed is not None else None
        time_end = parsed.end if parsed is not None else None

    events = list(await unified_memory.l1.search_events(query=query, limit=40))
    if time_start is not None:
        events = [event for event in events if _event_time(event) >= float(time_start)]
    if time_end is not None:
        events = [event for event in events if _event_time(event) <= float(time_end)]
    if not events and time_start is not None and time_end is not None:
        events = list(await unified_memory.l1.query_events(
            cognition_eligible=True,
            start_time=float(time_start),
            end_time=float(time_end),
            limit=200,
            order_by="timestamp_asc",
        ))
    if not events:
        return {
            "status": "insufficient",
            "draft": None,
            "choices": [],
            "message": "No grounded memory evidence matched this description.",
        }

    if time_start is None and time_end is None:
        credible_islands = [island for island in _time_islands(events) if len(island) >= 2]
        if len(credible_islands) > 1:
            return {
                "status": "ambiguous",
                "draft": None,
                "choices": _ambiguous_choices(credible_islands),
                "message": "Matching memories appear in more than one period.",
            }

    anchors = await _anchor_episodes(unified_memory.l2, events)
    if not anchors:
        return {
            "status": "insufficient",
            "draft": None,
            "choices": [],
            "message": "Matching events have not formed reliable source chapters yet.",
        }
    anchor_start = min(float(item["time_start"]) for item in anchors)
    anchor_end = max(float(item["time_end"]) for item in anchors)
    candidate_start = float(time_start) if time_start is not None else anchor_start - 4 * 60 * 60
    candidate_end = float(time_end) if time_end is not None else anchor_end + 4 * 60 * 60
    nearby = list(await unified_memory.l2.list_episodes(
        status="active",
        time_start=candidate_start,
        time_end=candidate_end,
        limit=100,
    ))
    episodes_by_id = {
        str(item["episode_id"]): item
        for item in [*anchors, *nearby]
        if str(item.get("episode_id") or "").strip()
    }
    candidates = sorted(
        episodes_by_id.values(),
        key=lambda item: float(item.get("time_start") or 0.0),
    )
    seed = {
        "seed_id": f"draft-request-{uuid.uuid4()}",
        "seed_type": "manual",
        "title": query,
        "description": query,
        "time_start": candidate_start,
        "time_end": candidate_end,
        "anchor_entity_ids": [],
        "anchor_place_ids": [],
        "anchor_topic_keys": [],
    }
    evidence_pack = {
        "seed": seed,
        "trigger_episode_ids": [str(item["episode_id"]) for item in anchors],
        "candidate_episodes": candidates,
        "candidate_event_ids": [str(item.get("event_id") or "") for item in events],
    }
    active_selector = selector or ExperienceSeedSelectionLLMService(
        scenario_llm_pool=getattr(unified_memory, "scenario_llm_pool", None),
    )
    selection = dict(await active_selector.select(seed, evidence_pack))
    if not selection.get("is_experience"):
        return {
            "status": "insufficient",
            "draft": None,
            "choices": [],
            "message": str(selection.get("reason") or "The evidence does not form one coherent experience."),
        }

    included_ids = [
        str(value)
        for value in (selection.get("included_episode_ids") or [])
        if str(value) in episodes_by_id
    ]
    if not included_ids:
        return {
            "status": "insufficient",
            "draft": None,
            "choices": [],
            "message": "No validated source chapters remained after review.",
        }
    excluded_by_id = {
        str(item.get("ref_id") or ""): item
        for item in (selection.get("excluded_refs") or [])
        if str(item.get("ref_type") or "episode") == "episode"
    }
    chapters = [
        _chapter_from_episode(episodes_by_id[episode_id], position=index)
        for index, episode_id in enumerate(included_ids)
    ]
    possible = [
        _episode_preview(episode)
        for episode_id, episode in episodes_by_id.items()
        if episode_id not in included_ids and episode_id not in excluded_by_id
    ]
    excluded = [
        {**_episode_preview(episodes_by_id[episode_id]), "reason": str(item.get("reason") or "")}
        for episode_id, item in excluded_by_id.items()
        if episode_id in episodes_by_id
    ]
    draft_id = str(uuid.uuid4())
    selected_start = min(float(episodes_by_id[item]["time_start"]) for item in included_ids)
    selected_end = max(float(episodes_by_id[item]["time_end"]) for item in included_ids)
    await unified_memory.l2.create_experience_draft(
        draft_id=draft_id,
        query_text=query,
        title=str(selection.get("title") or query).strip(),
        one_sentence_review=str(selection.get("one_sentence_review") or "").strip(),
        time_start=selected_start,
        time_end=selected_end,
        chapters=chapters,
        possible_evidence=possible,
        excluded_evidence=excluded,
    )
    return {
        "status": "draft",
        "draft": await unified_memory.l2.get_experience_draft(draft_id=draft_id),
        "choices": [],
        "message": None,
    }


__all__ = ["organize_experience_draft"]
