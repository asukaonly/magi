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
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_SENTENCE_END_RE = re.compile(r"[.!?。！？；;]\s*$")
_ENGLISH_INTENT_CLAUSE_RE = re.compile(
    r"\b(?:i|we)\s+(?:want|plan|hope|intend|need|will|shall|decided|would\s+like)\b",
    re.IGNORECASE,
)
_ENGLISH_TIME_ACTION_RE = re.compile(
    r"\b(?:tomorrow|tonight|next\s+(?:week|month|year)|someday|this\s+year)\b"
    r".{0,40}\b(?:go|visit|move|learn|start|finish|build|make|buy|attend|organize)\b",
    re.IGNORECASE,
)
_CHINESE_INTENT_ACTION_RE = re.compile(
    r"(?:我|我们)?(?:今年|明年|下周|下个月|以后|有一天|找时间)?"
    r"(?:想|希望|计划|准备|打算|需要|决定|要|会)"
    r".{0,12}(?:去|做|开始|完成|学习|整理|搬|住|买|看|参加|实现|建立|尝试)"
)
_CHINESE_TIME_ACTION_RE = re.compile(
    r"^(?:今天|明天|今年|明年|下周|下个月|以后|有一天|找时间)"
    r".{0,12}(?:去|做|开始|完成|学习|整理|搬|住|买|看|参加|实现|建立|尝试)"
)
_CHINESE_ACTION_RE = re.compile(
    r"散步|觅食|跑步|攀岩|旅行|学习|整理|开发|编程|搬家|居住|购买|观看|参加|建立|尝试"
)
_CHINESE_ACTION_JOIN_RE = re.compile(r"和|以及|并且|然后|再|同时")


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
    rejected_sentence_like_count = 0

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

        if _is_new_entity_candidate(entity) and (
            _is_sentence_like_entity_name(surface, entity_type=entity_type)
            or _is_sentence_like_entity_name(
                str(entity["normalized_name"]),
                entity_type=entity_type,
            )
        ):
            rejected_count += 1
            rejected_sentence_like_count += 1
            normalizations.append(
                f"entities[{index}]: dropped sentence-like new entity candidate"
            )
            continue

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
        "rejected_sentence_like_entity_count",
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
    if rejected_sentence_like_count:
        diagnostics["rejected_sentence_like_entity_count"] = rejected_sentence_like_count
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


def _is_new_entity_candidate(entity: dict[str, object]) -> bool:
    """Return whether a Phase 1 candidate would create catalog identity."""

    return _non_empty_text(entity.get("resolved_id")) is None


def _is_sentence_like_entity_name(value: str, *, entity_type: str) -> bool:
    """Reject clauses while retaining concise reusable catalog names."""

    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if not text:
        return False
    if "\n" in str(value) or "\r" in str(value):
        return True

    latin_words = _LATIN_WORD_RE.findall(text)
    cjk_length = len(_CJK_RE.findall(text))
    normalized_type = str(entity_type or "").strip().casefold()
    if normalized_type == "media":
        return len(text) > 200
    if len(latin_words) > 12 or cjk_length > 32:
        return True
    if _SENTENCE_END_RE.search(text) and (len(latin_words) >= 4 or cjk_length >= 6):
        return True
    if _ENGLISH_INTENT_CLAUSE_RE.search(text) or _ENGLISH_TIME_ACTION_RE.search(text):
        return True
    if _CHINESE_INTENT_ACTION_RE.search(text) or _CHINESE_TIME_ACTION_RE.search(text):
        return True
    chinese_actions = _CHINESE_ACTION_RE.findall(text)
    return bool(
        cjk_length >= 8
        and len(chinese_actions) >= 2
        and _CHINESE_ACTION_JOIN_RE.search(text)
    )


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
