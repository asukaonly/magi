"""Pure utility helpers shared by L2 pipeline mixins."""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional, cast

from ..models import L2BatchEvent, L2Phase1FactClaim, L2Phase1Result
from ..entities.identity import canonical_entity_id
from ..ontology import PROFILE_SIGNAL_PREDICATES, coerce_unknown_entity_type
from ..ontology_aliases import canonicalize_predicate

_GENERIC_PREFERENCE_OBJECT_SUFFIXES = {
    "weather",
    "weather-state",
    "food",
    "music",
    "place",
}

_ADDRESS_PREFERENCE_PATTERNS = (
    re.compile(r"(?:请|麻烦|以后|之后|往后|可以|就|直接)?(?:叫我|称呼我)(?:为|作|做|成)?[\s:：'\"“”‘’「」『』]*([^\s，。,.!?！？\n]+)"),
    re.compile(r"(?:call me|refer to me as|address me as)\s+['\"]?([^,.;!?\n]+)", re.IGNORECASE),
)
_ADDRESS_VALUE_STRIP_CHARS = " \t\r\n'\"“”‘’「」『』（）()[]{}<>《》：:，,。.!！?？"
_PROFILE_SIGNAL_VALUE_SEPARATOR_RE = re.compile(
    r"\s*(?:或者|还是|或是|以及|和|或|、|/|，|,|；|;|\bor\b|\band\b)\s*",
    re.IGNORECASE,
)


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

    def _extract_address_preference_values(self, text: str | None) -> set[str]:
        normalized = str(text or "").strip()
        if not normalized:
            return set()
        values: set[str] = set()
        for pattern in _ADDRESS_PREFERENCE_PATTERNS:
            for match in pattern.finditer(normalized):
                value = self._normalize_address_preference_value(match.group(1))
                if value:
                    values.add(value)
        return values

    def _is_address_preference_object(self, *, event_text: str | None, value: str | None) -> bool:
        candidate = self._normalize_address_preference_value(value)
        if not candidate:
            return False
        return candidate in self._extract_address_preference_values(event_text)

    def _normalize_address_preference_value(self, value: str | None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        _, _, suffix = text.partition(":")
        candidate = suffix or text
        candidate = candidate.strip(_ADDRESS_VALUE_STRIP_CHARS)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate.casefold() or None

    def _normalize_profile_signal_value(self, value: Any) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        _, _, suffix = text.partition(":")
        candidate = suffix or text
        candidate = candidate.strip(_ADDRESS_VALUE_STRIP_CHARS)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate.casefold() or None

    def _collect_profile_signal_object_refs(self, phase1_result: L2Phase1Result) -> set[str]:
        values: set[str] = set()
        for claim in phase1_result.fact_claims:
            predicate = self._normalize_predicate(claim.predicate)
            if predicate not in PROFILE_SIGNAL_PREDICATES:
                continue
            values.update(self._expand_profile_signal_values(claim.object_ref))
        return values

    def _filter_ungrounded_profile_signal_claims(
        self,
        phase1_result: L2Phase1Result,
        events: list[L2BatchEvent],
    ) -> int:
        user_texts = [
            str(event.content or "")
            for event in events
            if str(event.author_type or "").strip().casefold() == "user"
        ]
        if not user_texts:
            rejected_count = sum(
                1
                for claim in phase1_result.fact_claims
                if self._normalize_predicate(claim.predicate) in PROFILE_SIGNAL_PREDICATES
            )
            phase1_result.fact_claims = [
                claim
                for claim in phase1_result.fact_claims
                if self._normalize_predicate(claim.predicate) not in PROFILE_SIGNAL_PREDICATES
            ]
            return rejected_count

        filtered_claims: list[L2Phase1FactClaim] = []
        rejected_count = 0
        for claim in phase1_result.fact_claims:
            predicate = self._normalize_predicate(claim.predicate)
            if predicate not in PROFILE_SIGNAL_PREDICATES:
                filtered_claims.append(claim)
                continue
            if self._is_profile_signal_claim_grounded_in_user_text(claim, user_texts):
                filtered_claims.append(claim)
                continue
            rejected_count += 1
        phase1_result.fact_claims = filtered_claims
        return rejected_count

    def _is_profile_signal_claim_grounded_in_user_text(
        self,
        claim: L2Phase1FactClaim,
        user_texts: list[str],
    ) -> bool:
        fragments = [
            str(claim.evidence_text or "").strip(),
            str(claim.object_ref or "").strip(),
        ]
        fragments.extend(self._expand_profile_signal_values(claim.object_ref))
        normalized_fragments = [fragment for fragment in fragments if fragment]
        if not normalized_fragments:
            return False
        user_text_blob = "\n".join(user_texts).casefold()
        return any(fragment.casefold() in user_text_blob for fragment in normalized_fragments)

    def _expand_profile_signal_values(self, value: Any) -> set[str]:
        text = str(value or "").strip()
        if not text:
            return set()
        values: set[str] = set()
        normalized = self._normalize_profile_signal_value(text)
        if normalized:
            values.add(normalized)
        for part in _PROFILE_SIGNAL_VALUE_SEPARATOR_RE.split(text):
            normalized_part = self._normalize_profile_signal_value(part)
            if normalized_part:
                values.add(normalized_part)
        return values

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
        return canonical_entity_id(entity_type, canonical_name)

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
