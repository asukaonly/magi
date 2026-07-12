"""Ground user-like L2 references in external dialogue transcripts to speakers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...dialogue_transcripts import dialogue_speaker_entity_id, extract_dialogue_speaker
from ..models import (
    L2EventWindow,
    L2Phase1Entity,
    L2Phase1Result,
)


@dataclass(frozen=True, slots=True)
class _SpeakerRef:
    name: str
    entity_id: str


def ground_phase1_external_dialogue_refs(
    phase1_result: L2Phase1Result,
    event_window: L2EventWindow,
) -> dict[str, int]:
    """Rewrite external-dialogue ``user:*`` Phase 1 claims to the event speaker.

    The L2 prompt can still occasionally treat quoted first-person speech
    ("Caroline said, I...") as ``user:self``. For external dialogue transcripts,
    that is a data corruption bug: the fact belongs to Caroline, not the Magi
    user. Ambiguous mixed-speaker user claims are dropped instead of written to
    the wrong person.
    """
    speaker_by_event_id = _build_speaker_index(event_window)
    stats = {
        "rewritten_fact_claims": 0,
        "dropped_fact_claims": 0,
        "rewritten_resolved_refs": 0,
        "speaker_entity_count": 0,
    }
    if not speaker_by_event_id:
        return stats

    speakers = _unique_speakers(speaker_by_event_id.values())
    _ensure_speaker_entities(phase1_result, speakers)
    stats["speaker_entity_count"] = len(speakers)

    grounded_claims = []
    for claim in phase1_result.fact_claims:
        if not _is_user_ref(getattr(claim, "subject_ref", None), getattr(claim, "subject_type", None)):
            grounded_claims.append(claim)
            continue
        speaker = _resolve_item_speaker(
            event_window=event_window,
            speaker_by_event_id=speaker_by_event_id,
            supporting_event_ids=getattr(claim, "supporting_event_ids", None),
            evidence_texts=[getattr(claim, "evidence_text", "")],
        )
        if speaker is None:
            stats["dropped_fact_claims"] += 1
            continue
        claim.subject_ref = speaker.entity_id
        claim.subject_type = "person"
        grounded_claims.append(claim)
        stats["rewritten_fact_claims"] += 1
    phase1_result.fact_claims = grounded_claims

    for resolved_ref in phase1_result.resolved_refs:
        if not _is_user_ref(
            getattr(resolved_ref, "resolved_ref", None),
            getattr(resolved_ref, "resolved_kind", None),
        ):
            continue
        speaker = _resolve_item_speaker(
            event_window=event_window,
            speaker_by_event_id=speaker_by_event_id,
            supporting_event_ids=[],
            evidence_texts=[getattr(resolved_ref, "surface", "")],
        )
        if speaker is None:
            continue
        resolved_ref.resolved_ref = speaker.entity_id
        resolved_ref.resolved_kind = "person"
        stats["rewritten_resolved_refs"] += 1

    return stats


def _build_speaker_index(event_window: L2EventWindow) -> dict[str, _SpeakerRef]:
    result: dict[str, _SpeakerRef] = {}
    events = list(getattr(event_window, "events", []) or [])
    if events:
        for event in events:
            event_id = _non_empty_text(getattr(event, "event_id", None))
            if event_id is None:
                continue
            content = _non_empty_text(getattr(event, "content", None)) or ""
            speaker = _speaker_ref_for_event(event, content=content)
            if speaker is not None:
                result[event_id] = speaker
        return result

    for event_id, text in zip(
        list(getattr(event_window, "event_ids", []) or []),
        list(getattr(event_window, "texts", []) or []),
        strict=False,
    ):
        normalized_event_id = _non_empty_text(event_id)
        if normalized_event_id is None:
            continue
        speaker_name = extract_dialogue_speaker(str(text or ""))
        speaker_id = dialogue_speaker_entity_id(speaker_name)
        if speaker_name and speaker_id:
            result[normalized_event_id] = _SpeakerRef(name=speaker_name, entity_id=speaker_id)
    return result


def _speaker_ref_for_event(event: Any, *, content: str) -> _SpeakerRef | None:
    author_type = str(getattr(event, "author_type", "") or "").casefold()
    if author_type and author_type != "external":
        return None
    speaker_name = extract_dialogue_speaker(content)
    speaker_id = dialogue_speaker_entity_id(speaker_name)
    if speaker_name is None or speaker_id is None:
        return None
    return _SpeakerRef(name=speaker_name, entity_id=speaker_id)


def _resolve_item_speaker(
    *,
    event_window: L2EventWindow,
    speaker_by_event_id: dict[str, _SpeakerRef],
    supporting_event_ids: Any,
    evidence_texts: list[str],
) -> _SpeakerRef | None:
    speaker_candidates: dict[str, _SpeakerRef] = {}
    for event_id in _normalize_ids(supporting_event_ids):
        speaker = speaker_by_event_id.get(event_id)
        if speaker is not None:
            speaker_candidates[speaker.entity_id] = speaker
    if len(speaker_candidates) == 1:
        return next(iter(speaker_candidates.values()))
    if len(speaker_candidates) > 1:
        return None

    for text in evidence_texts:
        speaker_name = extract_dialogue_speaker(text)
        speaker_id = dialogue_speaker_entity_id(speaker_name)
        if speaker_name and speaker_id:
            return _SpeakerRef(name=speaker_name, entity_id=speaker_id)

    speaker = _resolve_speaker_from_evidence_texts(
        event_window=event_window,
        speaker_by_event_id=speaker_by_event_id,
        evidence_texts=evidence_texts,
    )
    if speaker is not None:
        return speaker

    all_speakers = _unique_speakers(speaker_by_event_id.values())
    if len(all_speakers) == 1 and _window_has_single_dialogue_event(event_window):
        return all_speakers[0]
    return None


def _ensure_speaker_entities(phase1_result: L2Phase1Result, speakers: list[_SpeakerRef]) -> None:
    existing_ids = {
        str(getattr(entity, "resolved_id", "") or "").casefold()
        for entity in phase1_result.entities
    }
    existing_names = {
        str(getattr(entity, "normalized_name", "") or "").casefold()
        for entity in phase1_result.entities
    }
    for speaker in speakers:
        if speaker.entity_id.casefold() in existing_ids or speaker.name.casefold() in existing_names:
            continue
        phase1_result.entities.append(
            L2Phase1Entity(
                surface=speaker.name,
                normalized_name=speaker.name,
                entity_type="person",
                resolved_id=speaker.entity_id,
                is_new=False,
                alias_signals=[speaker.name],
                confidence=1.0,
            )
        )


def _unique_speakers(speakers: Any) -> list[_SpeakerRef]:
    unique: dict[str, _SpeakerRef] = {}
    for speaker in speakers:
        if isinstance(speaker, _SpeakerRef):
            unique[speaker.entity_id] = speaker
    return list(unique.values())


def _window_has_single_dialogue_event(event_window: L2EventWindow) -> bool:
    event_count = len(list(getattr(event_window, "events", []) or []))
    if event_count > 0:
        return event_count == 1
    return len(list(getattr(event_window, "event_ids", []) or [])) == 1


def _resolve_speaker_from_evidence_texts(
    *,
    event_window: L2EventWindow,
    speaker_by_event_id: dict[str, _SpeakerRef],
    evidence_texts: list[str],
) -> _SpeakerRef | None:
    speaker_candidates: dict[str, _SpeakerRef] = {}
    event_texts = _iter_event_texts(event_window)
    if not event_texts:
        return None
    for evidence_text in evidence_texts:
        evidence = _normalize_match_text(evidence_text)
        if not _is_meaningful_evidence_match(evidence):
            continue
        for event_id, event_text in event_texts:
            speaker = speaker_by_event_id.get(event_id)
            if speaker is None:
                continue
            if evidence in _normalize_match_text(event_text):
                speaker_candidates[speaker.entity_id] = speaker
    if len(speaker_candidates) == 1:
        return next(iter(speaker_candidates.values()))
    return None


def _iter_event_texts(event_window: L2EventWindow) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    events = list(getattr(event_window, "events", []) or [])
    if events:
        for event in events:
            event_id = _non_empty_text(getattr(event, "event_id", None))
            content = _non_empty_text(getattr(event, "content", None))
            if event_id and content:
                result.append((event_id, content))
        return result

    for event_id, text in zip(
        list(getattr(event_window, "event_ids", []) or []),
        list(getattr(event_window, "texts", []) or []),
        strict=False,
    ):
        normalized_event_id = _non_empty_text(event_id)
        content = _non_empty_text(text)
        if normalized_event_id and content:
            result.append((normalized_event_id, content))
    return result


def _normalize_match_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return " ".join(text.split())


def _is_meaningful_evidence_match(evidence: str) -> bool:
    if len(evidence) < 12:
        return False
    return len(evidence.split()) >= 3


def _is_user_ref(ref: Any, ref_type: Any) -> bool:
    ref_text = str(ref or "").strip().casefold()
    type_text = str(ref_type or "").strip().casefold()
    return (
        ref_text in {"user", "self", "user:self"}
        or ref_text.startswith("user:")
        or (not ref_text and type_text == "user")
    )


def _normalize_ids(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    try:
        iterator = iter(values)
    except TypeError:
        return []
    result: list[str] = []
    for value in iterator:
        text = _non_empty_text(value)
        if text:
            result.append(text)
    return result


def _non_empty_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "dialogue_speaker_entity_id",
    "extract_dialogue_speaker",
    "ground_phase1_external_dialogue_refs",
]
