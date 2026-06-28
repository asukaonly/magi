"""Rule-based ownership screening for grounding-filter candidates."""

from __future__ import annotations

import re
from typing import Any

from magi.memory.dialogue_transcripts import extract_dialogue_speaker


def apply_named_person_owner_prefilter(
    query: str,
    events: list[dict[str, Any]],
    rels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Drop candidates that clearly belong to a different named person."""
    query_named_people = extract_query_named_people(query)
    if len(query_named_people) != 1:
        return {
            "events": events,
            "relationships": rels,
            "dropped_events": 0,
            "dropped_relationships": 0,
        }

    target_name = query_named_people[0]
    kept_events = [
        event for event in events if not _is_wrong_speaker_dialogue_event(event, target_name)
    ]
    kept_rels = [
        rel for rel in rels if not _is_wrong_subject_relationship(rel, target_name)
    ]
    return {
        "events": kept_events,
        "relationships": kept_rels,
        "dropped_events": len(events) - len(kept_events),
        "dropped_relationships": len(rels) - len(kept_rels),
    }


def extract_query_named_people(query: str) -> list[str]:
    text = str(query or "")
    if not text:
        return []
    stopwords = {
        "A",
        "An",
        "Are",
        "Can",
        "Did",
        "Do",
        "Does",
        "Has",
        "Have",
        "How",
        "I",
        "In",
        "Is",
        "On",
        "The",
        "What",
        "When",
        "Where",
        "Which",
        "Who",
        "Why",
    }
    names: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b([A-Z][a-z]+)(?:'s)?\b", text):
        name = match.group(1)
        if name in stopwords:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _is_wrong_speaker_dialogue_event(event: dict[str, Any], target_name: str) -> bool:
    content = str(event.get("content") or "")
    speaker = extract_dialogue_speaker(content)
    if not speaker:
        return False
    if _same_person_name(speaker, target_name):
        return False
    if _mentions_person_name(content, target_name):
        return False
    return True


def _is_wrong_subject_relationship(rel: dict[str, Any], target_name: str) -> bool:
    target_id = _person_entity_id_for_name(target_name)
    fields = [
        str(rel.get("subject_id") or ""),
        str(rel.get("subject_name") or ""),
        str(rel.get("object_id") or ""),
        str(rel.get("object_name") or ""),
        str(rel.get("natural_summary") or ""),
        str(rel.get("evidence_text") or ""),
    ]
    if any(_mentions_person_name(field, target_name) for field in fields):
        return False

    subject_id = str(rel.get("subject_id") or "").strip().casefold()
    subject_type = str(rel.get("subject_type") or "").strip().casefold()
    subject_name = str(rel.get("subject_name") or "").strip()
    subject_is_person = subject_id.startswith("person:") or subject_type == "person"
    if not subject_is_person:
        return False
    if target_id and subject_id == target_id:
        return False
    if subject_id.startswith("person:") and target_id and subject_id != target_id:
        return True
    if subject_name and not _same_person_name(subject_name, target_name):
        return True
    return False


def _same_person_name(left: str, right: str) -> bool:
    return _normalize_person_name(left) == _normalize_person_name(right)


def _mentions_person_name(text: str, name: str) -> bool:
    normalized_name = _normalize_person_name(name)
    if not normalized_name:
        return False
    pattern = rf"\b{re.escape(normalized_name)}(?:'s)?\b"
    return bool(re.search(pattern, str(text or "").casefold()))


def _person_entity_id_for_name(name: str) -> str | None:
    normalized = _normalize_person_name(name)
    if not normalized:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return f"person:{slug}" if slug else None


def _normalize_person_name(name: str) -> str:
    return " ".join(str(name or "").strip().casefold().split())


__all__ = ["apply_named_person_owner_prefilter", "extract_query_named_people"]
