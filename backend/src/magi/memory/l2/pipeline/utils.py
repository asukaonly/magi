"""Pure utility helpers shared by L2 pipeline mixins."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional, cast

from ..ontology import coerce_unknown_entity_type
from ..ontology_aliases import canonicalize_predicate

_GENERIC_PREFERENCE_OBJECT_SUFFIXES = {
    "weather",
    "weather-state",
    "food",
    "music",
    "place",
}


class L2PipelineUtilityMixin:
    """Own stat bucket, normalization, and canonical ID helpers."""

    def _increment_bucket(self, bucket: dict[str, int], key: str | None) -> None:
        if not key:
            return
        bucket[key] = int(bucket.get(key, 0)) + 1

    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        if text is None:
            return None
        return cast(str, coerce_unknown_entity_type(text))

    def _normalize_predicate(self, raw_value: Any) -> Optional[str]:
        text = self._non_empty_text(raw_value)
        if not text:
            return None
        return cast(str | None, canonicalize_predicate(text))

    def _normalize_structured_graph_hint_origin_mode(self, raw_value: Any) -> str:
        return str(self._non_empty_text(raw_value) or "source_structured").casefold()

    def _normalize_structured_graph_hint_page_kind(
        self, attributes: dict[str, Any] | None
    ) -> str | None:
        if not isinstance(attributes, dict):
            return None
        return str(self._non_empty_text(attributes.get("page_kind")) or "").casefold() or None

    def _extract_structured_graph_hint_facets(
        self,
        attributes: dict[str, Any] | None,
    ) -> list[tuple[str, str]]:
        if not isinstance(attributes, dict):
            return []

        raw_values: list[str] = []
        direct_value = self._non_empty_text(attributes.get("category"))
        if direct_value:
            raw_values.append(direct_value)
        raw_categories = attributes.get("categories")
        if isinstance(raw_categories, list):
            raw_values.extend(str(item).strip() for item in raw_categories if str(item).strip())

        facets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            normalized = str(raw_value).strip().casefold()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            facets.append(("category", normalized))
        return facets

    def _build_concept_node(self, *, entity_type: str, normalized_surface: str) -> Optional[str]:
        surface = self._non_empty_text(normalized_surface)
        if not surface:
            return None
        slug = self._slugify(surface)
        return f"{entity_type}:{slug}"

    def _looks_like_interrogative_preference_query(self, text: str | None) -> bool:
        normalized = str(text or "").strip().casefold()
        if not normalized:
            return False
        if any(
            marker in normalized
            for marker in ("?", "？", "什么", "哪种", "哪类", "是不是", "吗", "么")
        ):
            return True
        if any(
            marker in normalized
            for marker in ("你觉得", "你记得", "你知道", "guess", "do i ", "what ", "which ")
        ):
            return True
        return False

    def _is_generic_preference_object_id(self, value: str | None) -> bool:
        normalized = str(value or "").strip().casefold()
        if not normalized:
            return False
        _, _, suffix = normalized.partition(":")
        candidate = suffix or normalized
        return candidate in _GENERIC_PREFERENCE_OBJECT_SUFFIXES

    def _is_self_like_preference_object(
        self, *, subject_id: str, object_id: str, object_type: str
    ) -> bool:
        if object_id == subject_id:
            return True
        if object_type != "person":
            return False
        subject_prefix, _, subject_suffix = subject_id.partition(":")
        object_prefix, _, object_suffix = object_id.partition(":")
        if (
            subject_prefix != "user"
            or object_prefix != "person"
            or not subject_suffix
            or not object_suffix
        ):
            return False
        return self._slugify(subject_suffix) == object_suffix

    def _build_canonical_entity_id(self, *, entity_type: str, canonical_name: str) -> str:
        slug = self._slugify(canonical_name)
        return f"{entity_type}:{slug}"

    def _slugify(self, value: str) -> str:
        normalized = value.strip().casefold()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        if slug:
            return slug
        return uuid.uuid5(uuid.NAMESPACE_URL, normalized).hex[:12]

    def _non_empty_text(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _entity_type_from_id(self, entity_id: str) -> str:
        prefix, _, _ = entity_id.partition(":")
        return prefix or "entity"


__all__ = ["L2PipelineUtilityMixin"]
