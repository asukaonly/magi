"""Assertion candidate helpers for the L2 cognition pipeline."""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from ....event_contracts import MemoryEvent
from ...context_bundle import ResolvedContextRef
from ...extraction_profiles import ExtractionProfile
from ...models import L2AssertionCandidate, L2Phase1Result
from ...ontology import is_leaf_fact_duplicate, validate_assertion_candidate
from ...ontology_aliases import canonicalize_predicate
from ...storage.utils import normalize_event_ids

_TOPOLOGY_ONLY_TRAIT_FAMILIES = {"public_sentiment", "group_atmosphere", "relationship_shift"}
_SEMANTIC_TEMPORAL_SCOPES = {"persistent", "stable", ""}
_SEMANTIC_DECAY_POLICIES = {"none", "evidence_only", ""}
_PROFILE_TRAIT_BY_PREDICATE = {
    "REAL_NAME": "identity.real_name",
    "BIRTH_DATE": "identity.birth_date",
    "BIRTH_YEAR": "identity.birth_year",
    "STATED_AGE": "identity.age.stated",
    "PREFERRED_FORM_OF_ADDRESS": "communication.address.preferred",
    "DISALLOWED_FORM_OF_ADDRESS": "communication.address.disallowed",
    "PREFERRED_COMMUNICATION_STYLE": "communication.response_style.preferred",
}
_PROFILE_TRAITS_REQUIRING_PHASE1_SIGNAL = frozenset(_PROFILE_TRAIT_BY_PREDICATE.values())


def classify_memory_subdomain(temporal_scope: str, decay_policy: str) -> str:
    """Classify an assertion as 'semantic' or 'state' based on scope and decay."""
    if temporal_scope in _SEMANTIC_TEMPORAL_SCOPES and (
        decay_policy in _SEMANTIC_DECAY_POLICIES or not decay_policy
    ):
        return "semantic"
    return "state"


def _profile_values_by_trait(phase1_result: L2Phase1Result | None) -> dict[str, str]:
    if phase1_result is None:
        return {}
    values: dict[str, str] = {}
    for claim in phase1_result.fact_claims:
        predicate = canonicalize_predicate(getattr(claim, "predicate", ""))
        trait_name = _PROFILE_TRAIT_BY_PREDICATE.get(predicate or "")
        value = str(getattr(claim, "object_ref", "") or "").strip()
        if trait_name and value:
            values[trait_name] = value[:40]
    return values


def _profile_accepts_phase2_assertions(profile: ExtractionProfile) -> bool:
    mode = str(getattr(profile, "assertion_mode", "phase2_candidate") or "").strip().casefold()
    return mode in {"", "phase2_candidate"}


def _profile_allows_assertion_trait(profile: ExtractionProfile, trait_name: str) -> bool:
    allowed_traits = getattr(profile, "allowed_assertion_traits", None)
    if allowed_traits is None or allowed_traits == "all":
        return True
    allowed_iterable = [allowed_traits] if isinstance(allowed_traits, str) else allowed_traits
    normalized_trait = str(trait_name or "").strip().casefold()
    for item in allowed_iterable:
        pattern = str(item).strip().casefold()
        if not pattern:
            continue
        if pattern.endswith(".*") and normalized_trait.startswith(pattern[:-1]):
            return True
        if normalized_trait == pattern:
            return True
    return False


class _L2AssertionHostProtocol(Protocol):
    def _resolve_self_entity_id(self, event: MemoryEvent) -> str | None: ...

    def _non_empty_text(self, value: Any) -> Optional[str]: ...

    def _normalize_entity_type(self, raw_value: Any) -> Optional[str]: ...


class L2AssertionValidationMixin:
    """Own assertion normalization, decay, and scope filtering."""

    def _validate_phase2_assertions(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        default_event_ids: list[str],
        phase2_assertions: list,
        phase1_result: L2Phase1Result | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate Phase 2 assertion candidates."""
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0
        raw_assertions = list(phase2_assertions or [])
        if not _profile_accepts_phase2_assertions(profile):
            return [], len(raw_assertions)

        scoped_assertions = self._apply_assertion_scope(
            raw_candidates=raw_assertions,
            assertion_scope=getattr(policy, "assertion_scope", None) or "full",
        )

        host = self._assertion_host()
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_assertions) - len(scoped_assertions))
        duplicate_check_candidates = [
            {"predicate": c["predicate"], "object_ref": c["object_id"]} for c in graph_candidates
        ]
        profile_values_by_trait = _profile_values_by_trait(phase1_result)
        for assertion in scoped_assertions:
            trait_family = str(getattr(assertion, "trait_family", "") or "").casefold()
            if trait_family not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            trait_name = str(getattr(assertion, "trait_name", "") or "")
            if not _profile_allows_assertion_trait(profile, trait_name):
                rejected_count += 1
                continue
            assertion_dict = (
                assertion.to_dict() if hasattr(assertion, "to_dict") else dict(assertion)
            )
            is_valid, _ = validate_assertion_candidate(assertion_dict)
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, assertion_dict):
                rejected_count += 1
                continue

            self_entity_id = host._resolve_self_entity_id(event)
            entity_ref = host._non_empty_text(assertion.entity_ref)
            if entity_ref and entity_ref.startswith("user:") and self_entity_id:
                entity_ref = self_entity_id

            if (
                trait_name in _PROFILE_TRAITS_REQUIRING_PHASE1_SIGNAL
                and trait_name not in profile_values_by_trait
            ):
                rejected_count += 1
                continue
            trait_value = profile_values_by_trait.get(trait_name) or assertion.trait_value
            if isinstance(trait_value, (dict, list)):
                trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
            elif trait_value is None:
                trait_value = ""
            trait_value = str(trait_value)[:40]

            inference_depth = (
                host._non_empty_text(getattr(assertion, "inference_depth", ""))
                or event.tom_depth.label
            )
            volatility_index = float(getattr(assertion, "volatility_index", 0.5) or 0.5)

            temporal_scope, decay_policy, expires_at = self._derive_assertion_decay_from_family(
                event=event,
                trait_family=trait_family,
                trait_name=str(getattr(assertion, "trait_name", "") or ""),
            )

            prepared.append(
                {
                    "entity_id": entity_ref or self_entity_id or "",
                    "entity_type": str(getattr(assertion, "entity_type", "user") or "user"),
                    "trait_family": trait_family,
                    "trait_name": trait_name,
                    "trait_value": trait_value,
                    "confidence_score": float(getattr(assertion, "confidence", 0.0) or 0.0),
                    "evidence_events": normalize_event_ids(
                        getattr(assertion, "supporting_event_ids", None) or default_event_ids
                    ),
                    "volatility_index": volatility_index,
                    "source_domain": event.memory_domain.label,
                    "inference_depth": inference_depth,
                    "validation_state": "tentative",
                    "first_inferred_at": event.timestamp,
                    "last_validated_at": event.timestamp,
                    "target_entity_id": "",
                    "target_entity_type": "",
                    "target_scope": "global",
                    "temporal_scope": temporal_scope,
                    "decay_policy": decay_policy,
                    "decay_anchor_at": event.timestamp,
                    "context_ref_id": "",
                    "expires_at": expires_at,
                    "memory_subdomain": classify_memory_subdomain(temporal_scope, decay_policy),
                    "natural_summary": str(getattr(assertion, "natural_summary", "") or "")[:500],
                }
            )
        return prepared, rejected_count

    def _derive_assertion_decay_from_family(
        self,
        *,
        event: MemoryEvent,
        trait_family: str,
        trait_name: str,
    ) -> tuple[str, str, float | None]:
        """Derive decay policy from trait family and name."""
        name_lower = trait_name.casefold()
        if name_lower in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + 2 * 60 * 60
        if trait_family == "mood":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family == "stress":
            return "daily", "time_window", event.timestamp + 24 * 60 * 60
        if trait_family == "engagement":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return "session", "session_decay", event.timestamp + 6 * 60 * 60
        return "stable", "evidence_only", None

    def _prepare_unified_assertion_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        resolved_context_refs: list[ResolvedContextRef],
        default_event_ids: list[str],
        raw_candidates: list[L2AssertionCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        scoped_assertions = self._apply_assertion_scope(
            raw_candidates=raw_candidates,
            assertion_scope=policy.assertion_scope,
        )
        prepared: list[dict[str, Any]] = []
        rejected_count = max(0, len(raw_candidates) - len(scoped_assertions))
        duplicate_check_candidates = [
            {
                "predicate": candidate["predicate"],
                "object_ref": candidate["object_id"],
            }
            for candidate in graph_candidates
        ]
        for raw_candidate in scoped_assertions:
            if raw_candidate.trait_family.casefold() not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            is_valid, _ = validate_assertion_candidate(raw_candidate.to_dict())
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, raw_candidate.to_dict()):
                rejected_count += 1
                continue
            prepared.append(
                self._normalize_assertion_candidate(
                    event,
                    raw_candidate,
                    resolved_context_refs,
                    default_event_ids=default_event_ids,
                )
            )
        return prepared, rejected_count

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
        *,
        default_event_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        host = self._assertion_host()
        trait_value = candidate.trait_value
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        trait_value = str(trait_value)[:40]
        self_entity_id = host._resolve_self_entity_id(event)
        entity_ref = host._non_empty_text(candidate.entity_ref)
        if entity_ref and entity_ref.startswith("user:") and self_entity_id:
            entity_ref = self_entity_id
        target_entity_id, target_entity_type, context_ref_id = self._resolve_assertion_target(
            candidate=candidate,
            resolved_context_refs=resolved_context_refs,
        )
        temporal_scope, decay_policy, expires_at = self._derive_assertion_decay(
            event=event,
            candidate=candidate,
            target_entity_id=target_entity_id,
        )
        return {
            "entity_id": entity_ref or self_entity_id or "",
            "entity_type": candidate.entity_type or "user",
            "trait_family": candidate.trait_family.casefold(),
            "trait_name": candidate.trait_name,
            "trait_value": trait_value,
            "confidence_score": candidate.confidence,
            "evidence_events": normalize_event_ids(
                candidate.supporting_event_ids or default_event_ids or [event.event_id]
            ),
            "volatility_index": candidate.volatility_index,
            "source_domain": event.memory_domain.label,
            "inference_depth": candidate.inference_depth or event.tom_depth.label,
            "validation_state": candidate.validation_state or "tentative",
            "first_inferred_at": event.timestamp,
            "last_validated_at": event.timestamp,
            "target_entity_id": target_entity_id or "",
            "target_entity_type": target_entity_type or "",
            "target_scope": "entity_bound" if target_entity_id else "global",
            "temporal_scope": temporal_scope,
            "decay_policy": decay_policy,
            "decay_anchor_at": event.timestamp,
            "context_ref_id": context_ref_id or "",
            "expires_at": expires_at,
            "memory_subdomain": classify_memory_subdomain(temporal_scope, decay_policy),
            "natural_summary": str(getattr(candidate, "natural_summary", "") or "")[:500],
        }

    def _resolve_assertion_target(
        self,
        *,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
    ) -> tuple[str | None, str | None, str | None]:
        host = self._assertion_host()
        target_ref = host._non_empty_text(candidate.target_ref)
        explicit_target_entity_id = host._non_empty_text(candidate.target_entity_id)
        explicit_target_entity_type = host._normalize_entity_type(candidate.target_entity_type)
        if explicit_target_entity_id:
            return explicit_target_entity_id, explicit_target_entity_type, explicit_target_entity_id
        if not target_ref:
            return None, None, None
        target_ref_casefold = target_ref.casefold()
        for context_ref in resolved_context_refs:
            if (
                context_ref.surface
                and context_ref.resolved_ref
                and context_ref.surface.casefold() == target_ref_casefold
            ):
                kind = host._normalize_entity_type(
                    context_ref.resolved_kind
                ) or host._normalize_entity_type(context_ref.resolved_ref.split(":", 1)[0])
                return context_ref.resolved_ref, kind, context_ref.resolved_ref
        return None, None, None

    def _derive_assertion_decay(
        self,
        *,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        target_entity_id: str | None,
    ) -> tuple[str, str, float | None]:
        host = self._assertion_host()
        temporal_scope = host._non_empty_text(candidate.temporal_scope)
        decay_policy = host._non_empty_text(candidate.decay_policy)
        expires_at = candidate.expires_at
        if temporal_scope and decay_policy:
            return (
                temporal_scope,
                decay_policy,
                float(expires_at) if expires_at is not None else None,
            )

        trait_family = candidate.trait_family.casefold()
        trait_name = candidate.trait_name.casefold()
        if target_entity_id and trait_name in {"annoyance", "irritation", "frustration"}:
            return "momentary", "fast_decay", event.timestamp + 2 * 60 * 60
        if trait_family == "mood":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family == "stress":
            return "daily", "time_window", event.timestamp + 24 * 60 * 60
        if trait_family == "engagement":
            return "session", "session_decay", event.timestamp + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return "session", "session_decay", event.timestamp + 6 * 60 * 60
        return "stable", "evidence_only", None

    def _apply_assertion_scope(
        self,
        *,
        raw_candidates: list[Any],
        assertion_scope: str,
    ) -> list[Any]:
        if assertion_scope == "none":
            return []
        if assertion_scope == "full":
            return list(raw_candidates)
        if assertion_scope == "topology_only":
            return [
                candidate
                for candidate in raw_candidates
                if candidate.trait_family.casefold() in _TOPOLOGY_ONLY_TRAIT_FAMILIES
            ]
        return []

    def _assertion_host(self) -> _L2AssertionHostProtocol:
        return self  # type: ignore[return-value]
