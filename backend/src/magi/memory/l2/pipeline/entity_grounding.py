"""Deterministic evidence and script grounding for Phase 1 entities."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from ..models import L2BatchEvent, L2EventWindow
from .history_markdown import (
    HISTORY_DOCUMENT_EVENT_TYPE,
    find_history_document_author_occurrence,
)

_WHITESPACE_RE = re.compile(r"\s+")


def evidence_script_names(event_window: L2EventWindow) -> tuple[str, ...]:
    """Return the letter scripts present in the current eligible evidence."""

    scripts: set[str] = set()
    for _, content, _ in _eligible_evidence_sources(event_window):
        scripts.update(_letter_scripts(content))
    return tuple(sorted(scripts))


def normalize_phase1_entity_contract(
    payload: dict[str, object],
    event_window: L2EventWindow,
) -> list[str]:
    """Ground entity surfaces and aliases, repairing translated canonical names."""

    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list):
        return []

    eligible_sources = _eligible_evidence_sources(event_window)
    normalizations: list[str] = []
    kept_entities: list[dict[str, object]] = []
    name_replacements: dict[tuple[str, str], set[str]] = {}
    rejected_count = 0
    repaired_name_count = 0
    dropped_alias_count = 0

    for index, raw_entity in enumerate(raw_entities):
        if not isinstance(raw_entity, dict):
            rejected_count += 1
            normalizations.append(f"entities[{index}]: dropped non-object candidate")
            continue

        entity = dict(raw_entity)
        surface = _non_empty_text(entity.get("surface"))
        if surface is None or not _is_grounded_surface(surface, eligible_sources):
            rejected_count += 1
            normalizations.append(
                f"entities[{index}]: dropped candidate (missing exact current evidence)"
            )
            continue

        entity_type = _non_empty_text(entity.get("entity_type")) or ""
        raw_normalized_name = _non_empty_text(entity.get("normalized_name"))
        normalized_name = raw_normalized_name or surface
        if raw_normalized_name is None or _loses_source_script(surface, normalized_name):
            if raw_normalized_name and _canonical_text(raw_normalized_name) != _canonical_text(
                surface
            ):
                replacement_key = (
                    entity_type.casefold(),
                    _canonical_text(raw_normalized_name),
                )
                name_replacements.setdefault(replacement_key, set()).add(surface)
            entity["normalized_name"] = surface
            repaired_name_count += 1
            normalizations.append(
                f"entities[{index}].normalized_name: restored current evidence surface"
            )
        else:
            entity["normalized_name"] = normalized_name

        aliases = entity.get("alias_signals")
        grounded_aliases: list[str] = []
        seen_aliases: set[str] = {
            _canonical_text(surface),
            _canonical_text(entity["normalized_name"]),
        }
        if isinstance(aliases, list):
            for alias in aliases:
                alias_text = _non_empty_text(alias)
                if alias_text is None:
                    continue
                alias_key = _canonical_text(alias_text)
                if alias_key in seen_aliases:
                    continue
                if not _is_grounded_surface(alias_text, eligible_sources):
                    dropped_alias_count += 1
                    continue
                seen_aliases.add(alias_key)
                grounded_aliases.append(alias_text)
        entity["surface"] = surface
        entity["alias_signals"] = grounded_aliases
        kept_entities.append(entity)

    payload["entities"] = kept_entities
    rewritten_claim_ref_count = _rewrite_claim_entity_refs(payload, name_replacements)
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
        payload["diagnostics"] = diagnostics
    for key in (
        "rejected_entity_count",
        "repaired_entity_name_count",
        "dropped_entity_alias_count",
        "rewritten_claim_entity_ref_count",
    ):
        diagnostics.pop(key, None)
    diagnostics["entity_status"] = "found" if kept_entities else "none"
    if rejected_count:
        diagnostics["rejected_entity_count"] = rejected_count
    if repaired_name_count:
        diagnostics["repaired_entity_name_count"] = repaired_name_count
    if dropped_alias_count:
        diagnostics["dropped_entity_alias_count"] = dropped_alias_count
        normalizations.append(
            f"entities: dropped {dropped_alias_count} alias signals without current evidence"
        )
    if rewritten_claim_ref_count:
        diagnostics["rewritten_claim_entity_ref_count"] = rewritten_claim_ref_count
        normalizations.append(
            f"fact_claims: restored {rewritten_claim_ref_count} translated entity references"
        )
    return normalizations


def _eligible_evidence_sources(
    event_window: L2EventWindow,
) -> list[tuple[L2BatchEvent | None, str, bool]]:
    events = list(event_window.events)
    window_texts = list(event_window.texts)
    if not events:
        return [(None, text, False) for text in window_texts if str(text).strip()]

    texts_are_aligned = len(window_texts) == len(events)
    sources: list[tuple[L2BatchEvent | None, str, bool]] = []
    for index, event in enumerate(events):
        if str(event.author_type or "").strip().casefold() == "assistant":
            continue
        is_history_document = event.event_type == HISTORY_DOCUMENT_EVENT_TYPE
        content = (
            event.content if is_history_document or not texts_are_aligned else window_texts[index]
        )
        sources.append((event, content, is_history_document))
    return sources


def _is_grounded_surface(
    surface: str,
    eligible_sources: Iterable[tuple[L2BatchEvent | None, str, bool]],
) -> bool:
    canonical_surface = _canonical_text(surface)
    if not canonical_surface:
        return False
    for _, content, is_history_document in eligible_sources:
        if is_history_document:
            if find_history_document_author_occurrence(content, surface) is not None:
                return True
            continue
        if canonical_surface in _canonical_text(content):
            return True
    return False


def _loses_source_script(surface: str, normalized_name: str) -> bool:
    source_scripts = _letter_scripts(surface)
    normalized_scripts = _letter_scripts(normalized_name)
    return bool(source_scripts and not source_scripts.issubset(normalized_scripts))


def _letter_scripts(value: object) -> set[str]:
    scripts: set[str] = set()
    for character in unicodedata.normalize("NFKC", str(value or "")):
        if not unicodedata.category(character).startswith("L"):
            continue
        scripts.add(_letter_script(character))
    return scripts


def _letter_script(character: str) -> str:
    name = unicodedata.name(character, "")
    if "CJK" in name or "IDEOGRAPH" in name:
        return "Han"
    for marker, script in (
        ("HIRAGANA", "Hiragana"),
        ("KATAKANA", "Katakana"),
        ("HANGUL", "Hangul"),
        ("CYRILLIC", "Cyrillic"),
        ("LATIN", "Latin"),
        ("ARABIC", "Arabic"),
        ("HEBREW", "Hebrew"),
        ("DEVANAGARI", "Devanagari"),
        ("THAI", "Thai"),
        ("GREEK", "Greek"),
    ):
        if marker in name:
            return script
    return "Other"


def _rewrite_claim_entity_refs(
    payload: dict[str, object],
    replacements: dict[tuple[str, str], set[str]],
) -> int:
    raw_claims = payload.get("fact_claims")
    if not replacements or not isinstance(raw_claims, list):
        return 0
    rewritten_count = 0
    for claim in raw_claims:
        if not isinstance(claim, dict):
            continue
        for ref_field, type_field in (
            ("subject_ref", "subject_type"),
            ("object_ref", "object_type"),
        ):
            ref = _non_empty_text(claim.get(ref_field))
            ref_type = _non_empty_text(claim.get(type_field))
            if ref is None or ref_type is None:
                continue
            candidates = replacements.get((ref_type.casefold(), _canonical_text(ref)))
            if candidates is None or len(candidates) != 1:
                continue
            claim[ref_field] = next(iter(candidates))
            rewritten_count += 1
    return rewritten_count


def _canonical_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _WHITESPACE_RE.sub(" ", text).strip()


def _non_empty_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "evidence_script_names",
    "normalize_phase1_entity_contract",
]
