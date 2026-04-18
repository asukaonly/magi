"""Validation and candidate preparation methods for L2Pipeline."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from .context_bundle import ResolvedContextRef
from .models import (
    ContradictionHint,
    L2AssertionCandidate,
    L2GraphCandidate,
    L2Phase1FactClaim,
    L2Phase1Result,
    L2Phase2ContradictionHint,
    L2Phase2GraphEdge,
    ResolvedEntityMention,
    StructuredGraphHint,
)
from .extraction_profiles import ExtractionProfile
from .ontology import (
    OPEN_PREDICATE_CONFIDENCE_PENALTY,
    PREDICATE_REGISTRY,
    is_leaf_fact_duplicate,
    is_valid_open_predicate,
    validate_assertion_candidate,
    validate_graph_candidate,
)

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_PREFERENCE_PREDICATES = {"LIKES", "DISLIKES", "INTERESTED_IN"}
_TOPOLOGY_ONLY_TRAIT_FAMILIES = {"public_sentiment", "group_atmosphere", "relationship_shift"}
_GENERIC_PREFERENCE_OBJECT_SUFFIXES = {
    "weather",
    "weather-state",
    "food",
    "music",
    "place",
}
_STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS = {"public_topology", "interaction_evidence", "explicit_fact"}
_STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES = {"source_explicit", "source_structured"}

# P2: memory subdomain classification — stable/persistent + evidence-only → semantic
_SEMANTIC_TEMPORAL_SCOPES = {"persistent", "stable", ""}
_SEMANTIC_DECAY_POLICIES = {"none", "evidence_only", ""}


def classify_memory_subdomain(temporal_scope: str, decay_policy: str) -> str:
    """Classify an assertion as 'semantic' or 'state' based on its temporal scope and decay policy."""
    if temporal_scope in _SEMANTIC_TEMPORAL_SCOPES and (
        decay_policy in _SEMANTIC_DECAY_POLICIES or not decay_policy
    ):
        return "semantic"
    return "state"
_STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS = {
    "creator_profile",
    "creator_home",
    "creator_channel",
    "subscription",
    "subscriptions",
}


class L2ValidationMixin:
    """Mixin providing validation, candidate preparation, and structured hint methods for L2Pipeline."""

    def _inject_structured_entity_hints(
        self,
        event: MemoryEvent,
        existing_entities: list[dict[str, Any]],
    ) -> None:
        """Inject structured entity hints into existing_entities as Phase 1 context."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_entity_hints")
        if not hints or not isinstance(hints, list):
            return

        existing_ids = {str(e.get("entity_id", "")) for e in existing_entities}
        injected_count = 0
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            mention_text = str(hint.get("mention_text", "")).strip()
            entity_type = self._normalize_entity_type(hint.get("entity_type"))  # type: ignore[attr-defined]
            if not mention_text or not entity_type:
                continue

            canonical_name = str(hint.get("canonical_name_hint") or mention_text).strip()
            resolved_id = hint.get("resolved_entity_id")
            if resolved_id:
                entity_id = str(resolved_id)
            else:
                entity_id = self._build_canonical_entity_id(  # type: ignore[attr-defined]
                    entity_type=entity_type, canonical_name=canonical_name,
                )

            if entity_id in existing_ids:
                continue

            existing_entities.append({
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "aliases": [canonical_name],
                "hint_only": True,
            })
            existing_ids.add(entity_id)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured entity hints injected as context",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )

    def _inject_structured_graph_hints(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
    ) -> None:
        """Inject structured graph hints as deterministic Phase 1 fact claims."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return
        hints = metadata_json.get("structured_graph_hints")
        if not hints or not isinstance(hints, list):
            return

        existing_keys = {
            (
                self._non_empty_text(claim.subject_ref) or "",  # type: ignore[attr-defined]
                self._normalize_predicate(claim.predicate) or "",  # type: ignore[attr-defined]
                self._non_empty_text(claim.object_ref) or "",  # type: ignore[attr-defined]
                self._normalize_entity_type(claim.object_type) or "",  # type: ignore[attr-defined]
            )
            for claim in phase1_result.fact_claims
        }

        injected_count = 0
        for raw_hint in hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            subject_ref = self._non_empty_text(hint.subject_ref)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(hint.predicate)  # type: ignore[attr-defined]
            object_ref = self._non_empty_text(hint.object_ref)  # type: ignore[attr-defined]
            object_type = self._normalize_entity_type(hint.object_type)  # type: ignore[attr-defined]
            subject_type = self._non_empty_text(hint.subject_type) or "user"  # type: ignore[attr-defined]
            if not subject_ref or not predicate or not object_ref or not object_type:
                continue

            hint_key = (subject_ref, predicate, object_ref, object_type)
            if hint_key in existing_keys:
                continue

            phase1_result.fact_claims.append(
                L2Phase1FactClaim(
                    subject_ref=subject_ref,
                    subject_type=subject_type,
                    predicate=predicate,
                    object_ref=object_ref,
                    object_type=object_type,
                    fact_kind=self._non_empty_text(hint.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
                    polarity="positive",
                    specificity="concrete",
                    evidence_text=self._non_empty_text(hint.evidence_text) or "",  # type: ignore[attr-defined]
                    confidence=float(hint.confidence if hint.confidence is not None else 1.0),
                    supporting_event_ids=[event.event_id],
                )
            )
            existing_keys.add(hint_key)
            injected_count += 1

        if injected_count:
            logger.debug(
                "L2 structured graph hints injected as fact claims",
                event_id=event.event_id,
                hint_count=len(hints),
                injected_count=injected_count,
            )

    def _validate_phase2_graph_edges(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        evidence_event_ids: list[str],
        phase2_edges: list[L2Phase2GraphEdge],
        catalog_name_index: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Validate Phase 2 graph edges against ontology and profile constraints."""
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], [], 0

        prepared: list[dict[str, Any]] = []
        corroborate_targets: list[dict[str, Any]] = []
        rejected_count = 0
        for edge in phase2_edges:
            if edge.relationship_to_existing == "corroborates" and edge.related_existing_triple_id:
                corroborate_targets.append({
                    "triple_id": edge.related_existing_triple_id,
                    "evidence_event_ids": list(edge.supporting_event_ids or evidence_event_ids),
                    "new_confidence": edge.confidence,
                    "observed_at": event.timestamp,
                    "evidence_text": edge.evidence_text or "",
                })
                continue

            object_type = self._normalize_entity_type(edge.object_type)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(edge.predicate)  # type: ignore[attr-defined]
            if object_type not in profile.effective_structured_allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.effective_structured_allowed_predicates and not (
                profile.effective_structured_allowed_predicates >= PREDICATE_REGISTRY
                and is_valid_open_predicate(predicate)
            ):
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {"predicate": predicate, "object_type": object_type}
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=edge.subject_ref)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=edge.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=edge.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": edge.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "fact_kind": self._non_empty_text(edge.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
                    "evidence_event_ids": list(edge.supporting_event_ids or evidence_event_ids),
                    "confidence": (
                        edge.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                        if predicate not in PREDICATE_REGISTRY
                        else edge.confidence
                    ),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_phase2_integration",
                    "evidence_text": edge.evidence_text or "",
                }
            )
        return prepared, corroborate_targets, rejected_count

    def _can_fast_track(
        self,
        *,
        phase1_result: L2Phase1Result,
        resolved_mentions: list[ResolvedEntityMention],
        existing_graph_edges: list[dict[str, Any]],
        profile: ExtractionProfile,
        policy: Any,
    ) -> bool:
        """Return True when Phase 1 output is simple enough to skip Phase 2."""
        if not phase1_result.fact_claims:
            return False
        if policy.allow_assertion_write:
            return False
        for claim in phase1_result.fact_claims:
            if self._normalize_predicate(claim.predicate) not in PREDICATE_REGISTRY:  # type: ignore[attr-defined]
                return False
        for entity in phase1_result.entities:
            if getattr(entity, "is_new", False):
                return False
        if any(
            claim.fact_kind and "assertion" in claim.fact_kind.lower()
            for claim in phase1_result.fact_claims
        ):
            return False
        existing_predicates_by_pair: dict[tuple[str, str], set[str]] = {}
        for edge in existing_graph_edges:
            pair = (str(edge.get("subject_id", "")), str(edge.get("object_id", "")))
            existing_predicates_by_pair.setdefault(pair, set()).add(str(edge.get("predicate", "")))
        for claim in phase1_result.fact_claims:
            predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
            object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=None,
            )
            if not object_id:
                return False
            if object_type not in profile.effective_structured_allowed_entity_types:
                return False
            if predicate not in profile.effective_structured_allowed_predicates:
                return False
        return True

    def _fast_track_claims_to_candidates(
        self,
        *,
        phase1_result: L2Phase1Result,
        event: MemoryEvent,
        evidence_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
        profile: ExtractionProfile,
    ) -> list[dict[str, Any]]:
        """Convert Phase 1 fact claims directly to graph candidates (no Phase 2)."""
        candidates: list[dict[str, Any]] = []
        for claim in phase1_result.fact_claims:
            predicate = self._normalize_predicate(claim.predicate)  # type: ignore[attr-defined]
            object_type = self._normalize_entity_type(claim.object_type)  # type: ignore[attr-defined]
            if object_type not in profile.effective_structured_allowed_entity_types:
                continue
            if predicate not in profile.effective_structured_allowed_predicates:
                continue
            is_valid, _ = validate_graph_candidate({"predicate": predicate, "object_type": object_type})
            if not is_valid:
                continue
            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=claim.subject_ref)
            if not subject_id:
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=claim.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=claim.object_ref,
            ):
                continue
            candidates.append({
                "subject_id": subject_id,
                "subject_type": claim.subject_type or "user",
                "predicate": predicate,
                "object_id": object_id,
                "object_type": object_type,
                "fact_kind": self._non_empty_text(claim.fact_kind) or "explicit_fact",  # type: ignore[attr-defined]
                "evidence_event_ids": list(claim.supporting_event_ids or evidence_event_ids),
                "confidence": claim.confidence,
                "observed_at": event.timestamp,
                "source_type": event.source,
                "extraction_method": "llm_phase1_fast_track",
                "evidence_text": claim.evidence_text or "",
            })
        return candidates

    def _build_structured_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        evidence_event_ids: list[str],
        catalog_name_index: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Convert source-owned structured graph hints into deterministic graph candidates."""
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return [], 0
        raw_hints = metadata_json.get("structured_graph_hints")
        if not isinstance(raw_hints, list) or not raw_hints:
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_hint in raw_hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            object_type = self._normalize_entity_type(hint.object_type)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(hint.predicate)  # type: ignore[attr-defined]
            fact_kind = self._non_empty_text(hint.fact_kind) or "explicit_fact"  # type: ignore[attr-defined]
            if fact_kind not in _STRUCTURED_GRAPH_HINT_DIRECT_FACT_KINDS:
                rejected_count += 1
                continue
            if not self._is_structured_graph_hint_directly_admissible(hint=hint, predicate=predicate, fact_kind=fact_kind):
                rejected_count += 1
                continue
            if object_type not in profile.effective_structured_allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.effective_structured_allowed_predicates:
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate({"predicate": predicate, "object_type": object_type})
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=hint.subject_ref)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_phase2_object_id(
                raw_object_ref=hint.object_ref,
                object_type=object_type,
                resolved_mentions=[],
                catalog_name_index=catalog_name_index,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=hint.object_ref,
            ):
                rejected_count += 1
                continue

            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": self._non_empty_text(hint.subject_type) or "user",  # type: ignore[attr-defined]
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "fact_kind": fact_kind,
                    "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                    "confidence": float(hint.confidence if hint.confidence is not None else 1.0),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "structured_hint",
                }
            )
        return prepared, rejected_count

    def _build_structured_facet_candidates(
        self,
        *,
        event: MemoryEvent,
        evidence_event_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Convert source-owned structured graph hint attributes into sidecar entity facets."""
        metadata_json = event.metadata_json
        if not isinstance(metadata_json, dict):
            return []
        raw_hints = metadata_json.get("structured_graph_hints")
        if not isinstance(raw_hints, list) or not raw_hints:
            return []

        prepared: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for raw_hint in raw_hints:
            if not isinstance(raw_hint, dict):
                continue
            hint = StructuredGraphHint.from_dict(raw_hint)
            origin_mode = self._normalize_structured_graph_hint_origin_mode(hint.origin_mode)  # type: ignore[attr-defined]
            if origin_mode not in _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES:
                continue
            subject_id = self._resolve_phase2_subject_id(event=event, subject_ref=hint.subject_ref)
            subject_type = self._normalize_entity_type(hint.subject_type)  # type: ignore[attr-defined]
            if not subject_id or not subject_type:
                continue
            for facet_name, facet_value in self._extract_structured_graph_hint_facets(hint.attributes):  # type: ignore[attr-defined]
                key = (subject_id, facet_name, facet_value)
                if key in seen:
                    continue
                seen.add(key)
                prepared.append(
                    {
                        "entity_id": subject_id,
                        "entity_type": subject_type,
                        "facet_name": facet_name,
                        "facet_value": facet_value,
                        "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                        "confidence": float(hint.confidence if hint.confidence is not None else 1.0),
                        "observed_at": event.timestamp,
                        "source_type": event.source,
                        "extraction_method": "structured_hint",
                    }
                )
        return prepared

    def _is_structured_graph_hint_directly_admissible(
        self,
        *,
        hint: StructuredGraphHint,
        predicate: str | None,
        fact_kind: str,
    ) -> bool:
        """Return whether a source-owned graph hint may bypass LLM edge generation."""
        canonical_predicate = self._normalize_predicate(predicate)  # type: ignore[attr-defined]
        if canonical_predicate is None:
            return False

        origin_mode = self._normalize_structured_graph_hint_origin_mode(hint.origin_mode)  # type: ignore[attr-defined]
        if origin_mode not in _STRUCTURED_GRAPH_HINT_DIRECT_ORIGIN_MODES:
            return False

        if fact_kind in {"public_topology", "explicit_fact"}:
            return True

        if fact_kind != "interaction_evidence":
            return False

        if canonical_predicate != "FOLLOWS":
            return True

        page_kind = self._normalize_structured_graph_hint_page_kind(hint.attributes)  # type: ignore[attr-defined]
        return page_kind in _STRUCTURED_GRAPH_HINT_FOLLOWS_PAGE_KINDS

    def _merge_graph_candidates(self, *candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge graph candidates by triple identity, preferring structured hints."""
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for group in candidate_groups:
            for candidate in group:
                key = (
                    str(candidate.get("subject_id") or ""),
                    str(candidate.get("predicate") or ""),
                    str(candidate.get("object_id") or ""),
                )
                if not all(key):
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = dict(candidate)
                    continue

                existing_method = str(existing.get("extraction_method") or "")
                candidate_method = str(candidate.get("extraction_method") or "")
                preferred = dict(candidate) if candidate_method == "structured_hint" and existing_method != "structured_hint" else dict(existing)
                preferred["evidence_event_ids"] = sorted(
                    set(existing.get("evidence_event_ids") or []).union(candidate.get("evidence_event_ids") or [])
                )
                preferred["confidence"] = max(
                    float(existing.get("confidence") or 0.0),
                    float(candidate.get("confidence") or 0.0),
                )
                preferred["fact_kind"] = (
                    str(candidate.get("fact_kind") or "").strip()
                    if candidate_method == "structured_hint" and str(candidate.get("fact_kind") or "").strip()
                    else str(preferred.get("fact_kind") or existing.get("fact_kind") or candidate.get("fact_kind") or "explicit_fact")
                )
                merged[key] = preferred
        return list(merged.values())

    def _validate_phase2_assertions(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        graph_candidates: list[dict[str, Any]],
        default_event_ids: list[str],
        phase2_assertions: list,
    ) -> tuple[list[dict[str, Any]], int]:
        """Validate Phase 2 assertion candidates."""
        if not policy.allow_assertion_write or not profile.allow_assertion:
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        duplicate_check_candidates = [
            {"predicate": c["predicate"], "object_ref": c["object_id"]}
            for c in graph_candidates
        ]
        for assertion in phase2_assertions:
            trait_family = str(getattr(assertion, "trait_family", "") or "").casefold()
            if trait_family not in profile.allowed_assertion_families:
                rejected_count += 1
                continue
            assertion_dict = assertion.to_dict() if hasattr(assertion, "to_dict") else dict(assertion)
            is_valid, _ = validate_assertion_candidate(assertion_dict)
            if not is_valid:
                rejected_count += 1
                continue
            if is_leaf_fact_duplicate(duplicate_check_candidates, assertion_dict):
                rejected_count += 1
                continue

            self_entity_id = self._resolve_self_entity_id(event)  # type: ignore[attr-defined]
            entity_ref = self._non_empty_text(assertion.entity_ref)  # type: ignore[attr-defined]
            if entity_ref and entity_ref.startswith("user:") and self_entity_id:
                entity_ref = self_entity_id

            trait_value = assertion.trait_value
            if isinstance(trait_value, (dict, list)):
                trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
            elif trait_value is None:
                trait_value = ""

            inference_depth = self._non_empty_text(getattr(assertion, "inference_depth", "")) or event.tom_depth.label  # type: ignore[attr-defined]
            volatility_index = float(getattr(assertion, "volatility_index", 0.5) or 0.5)

            temporal_scope, decay_policy, expires_at = self._derive_assertion_decay_from_family(
                event=event,
                trait_family=trait_family,
                trait_name=str(getattr(assertion, "trait_name", "") or ""),
            )

            prepared.append({
                "entity_id": entity_ref or self_entity_id or "",
                "entity_type": str(getattr(assertion, "entity_type", "user") or "user"),
                "trait_family": trait_family,
                "trait_name": str(getattr(assertion, "trait_name", "") or ""),
                "trait_value": str(trait_value),
                "confidence_score": float(getattr(assertion, "confidence", 0.0) or 0.0),
                "evidence_events": list(getattr(assertion, "supporting_event_ids", None) or default_event_ids),
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
            })
        return prepared, rejected_count

    def _convert_phase2_contradiction_hints(
        self,
        phase2_hints: list[L2Phase2ContradictionHint],
    ) -> list[ContradictionHint]:
        """Convert Phase 2 contradiction hints to the ContradictionHint format."""
        hints: list[ContradictionHint] = []
        for h in phase2_hints:
            if not h.target_record_id or not h.target_record_type or not h.contradiction_kind:
                continue
            hints.append(
                ContradictionHint(
                    target_record_id=h.target_record_id,
                    target_record_type=h.target_record_type,
                    contradiction_kind=h.contradiction_kind,
                    confidence=h.confidence,
                    evidence_text=h.evidence_text,
                    recommended_action=h.recommended_action,
                )
            )
        return hints

    def _resolve_phase2_subject_id(self, *, event: MemoryEvent, subject_ref: str) -> str | None:
        ref = self._non_empty_text(subject_ref)  # type: ignore[attr-defined]
        if ref:
            if ref.startswith("user:"):
                return self._resolve_self_entity_id(event) or ref  # type: ignore[attr-defined]
            return ref
        return self._resolve_self_entity_id(event)  # type: ignore[attr-defined]

    def _resolve_phase2_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        object_ref = self._non_empty_text(raw_object_ref)  # type: ignore[attr-defined]
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = self._non_empty_text(mention.resolved_entity_id)  # type: ignore[attr-defined]
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        if catalog_name_index:
            catalog_hit = catalog_name_index.get(object_ref_casefold)
            if catalog_hit:
                return catalog_hit
        return self._build_concept_node(entity_type=object_type, normalized_surface=object_ref)  # type: ignore[attr-defined]

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

    def _prepare_unified_graph_candidates(
        self,
        *,
        event: MemoryEvent,
        profile: ExtractionProfile,
        policy: Any,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        evidence_event_ids: list[str],
        raw_candidates: list[L2GraphCandidate],
    ) -> tuple[list[dict[str, Any]], int]:
        if not policy.allow_graph_write or not profile.allow_graph or policy.graph_scope != "full":
            return [], 0

        prepared: list[dict[str, Any]] = []
        rejected_count = 0
        for raw_candidate in raw_candidates:
            object_type = self._normalize_entity_type(raw_candidate.object_type)  # type: ignore[attr-defined]
            predicate = self._normalize_predicate(raw_candidate.predicate)  # type: ignore[attr-defined]
            if object_type not in profile.allowed_entity_types:
                rejected_count += 1
                continue
            if predicate not in profile.allowed_predicates and not (
                profile.allowed_predicates >= PREDICATE_REGISTRY
                and is_valid_open_predicate(predicate)
            ):
                rejected_count += 1
                continue
            is_valid, _ = validate_graph_candidate(
                {
                    "predicate": predicate,
                    "object_type": object_type,
                }
            )
            if not is_valid:
                rejected_count += 1
                continue

            subject_id = self._resolve_subject_id(event=event, raw_candidate=raw_candidate)
            if not subject_id:
                rejected_count += 1
                continue
            object_id = self._resolve_graph_object_id(
                raw_object_ref=raw_candidate.object_ref,
                object_type=object_type,
                resolved_mentions=resolved_mentions,
                resolved_context_refs=resolved_context_refs,
            )
            if not object_id:
                rejected_count += 1
                continue
            if self._should_reject_preference_graph_candidate(
                event=event,
                subject_id=subject_id,
                predicate=predicate,
                object_id=object_id,
                object_type=object_type,
                raw_object_ref=raw_candidate.object_ref,
            ):
                rejected_count += 1
                continue
            prepared.append(
                {
                    "subject_id": subject_id,
                    "subject_type": raw_candidate.subject_type or "user",
                    "predicate": predicate,
                    "object_id": object_id,
                    "object_type": object_type,
                    "evidence_event_ids": list(evidence_event_ids or [event.event_id]),
                    "confidence": (
                        raw_candidate.confidence * OPEN_PREDICATE_CONFIDENCE_PENALTY
                        if predicate not in PREDICATE_REGISTRY
                        else raw_candidate.confidence
                    ),
                    "observed_at": event.timestamp,
                    "source_type": event.source,
                    "extraction_method": "llm_two_phase_extraction",
                }
            )
        return prepared, rejected_count

    def _should_reject_preference_graph_candidate(
        self,
        *,
        event: MemoryEvent,
        subject_id: str,
        predicate: str,
        object_id: str,
        object_type: str,
        raw_object_ref: str,
    ) -> bool:
        if predicate not in _PREFERENCE_PREDICATES:
            return False
        if self._looks_like_interrogative_preference_query(event.content):  # type: ignore[attr-defined]
            return True
        if self._is_generic_preference_object_id(object_id) or self._is_generic_preference_object_id(raw_object_ref):  # type: ignore[attr-defined]
            return True
        if self._is_self_like_preference_object(subject_id=subject_id, object_id=object_id, object_type=object_type):  # type: ignore[attr-defined]
            return True
        return False

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

    def _resolve_subject_id(self, *, event: MemoryEvent, raw_candidate: L2GraphCandidate) -> str | None:
        subject_ref = self._non_empty_text(raw_candidate.subject_ref)  # type: ignore[attr-defined]
        if subject_ref:
            if subject_ref.startswith("user:"):
                return self._resolve_self_entity_id(event) or subject_ref  # type: ignore[attr-defined]
            return subject_ref
        return self._resolve_self_entity_id(event)  # type: ignore[attr-defined]

    def _resolve_graph_object_id(
        self,
        *,
        raw_object_ref: Any,
        object_type: str,
        resolved_mentions: list[ResolvedEntityMention],
        resolved_context_refs: list[ResolvedContextRef],
        catalog_name_index: dict[str, str] | None = None,
    ) -> str | None:
        object_ref = self._non_empty_text(raw_object_ref)  # type: ignore[attr-defined]
        if not object_ref:
            return None
        if ":" in object_ref:
            return object_ref
        object_ref_casefold = object_ref.casefold()
        for context_ref in resolved_context_refs:
            if context_ref.surface and context_ref.resolved_ref and context_ref.surface.casefold() == object_ref_casefold:
                return context_ref.resolved_ref
        for mention in resolved_mentions:
            surfaces = {
                mention.mention_text.strip().casefold(),
                mention.normalized_surface.strip().casefold(),
            }
            resolved_entity_id = self._non_empty_text(mention.resolved_entity_id)  # type: ignore[attr-defined]
            if object_ref_casefold in surfaces and resolved_entity_id:
                return resolved_entity_id
        if catalog_name_index:
            catalog_hit = catalog_name_index.get(object_ref_casefold)
            if catalog_hit:
                return catalog_hit
        return self._build_concept_node(entity_type=object_type, normalized_surface=object_ref)  # type: ignore[attr-defined]

    def _normalize_assertion_candidate(
        self,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
        *,
        default_event_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        trait_value = candidate.trait_value
        if isinstance(trait_value, (dict, list)):
            trait_value = json.dumps(trait_value, ensure_ascii=False, sort_keys=True)
        elif trait_value is None:
            trait_value = ""
        self_entity_id = self._resolve_self_entity_id(event)  # type: ignore[attr-defined]
        entity_ref = self._non_empty_text(candidate.entity_ref)  # type: ignore[attr-defined]
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
            "trait_value": str(trait_value),
            "confidence_score": candidate.confidence,
            "evidence_events": list(candidate.supporting_event_ids or default_event_ids or [event.event_id]),
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
        }

    def _resolve_assertion_target(
        self,
        *,
        candidate: L2AssertionCandidate,
        resolved_context_refs: list[ResolvedContextRef],
    ) -> tuple[str | None, str | None, str | None]:
        target_ref = self._non_empty_text(candidate.target_ref)  # type: ignore[attr-defined]
        explicit_target_entity_id = self._non_empty_text(candidate.target_entity_id)  # type: ignore[attr-defined]
        explicit_target_entity_type = self._normalize_entity_type(candidate.target_entity_type)  # type: ignore[attr-defined]
        if explicit_target_entity_id:
            return explicit_target_entity_id, explicit_target_entity_type, explicit_target_entity_id
        if not target_ref:
            return None, None, None
        target_ref_casefold = target_ref.casefold()
        for context_ref in resolved_context_refs:
            if context_ref.surface and context_ref.resolved_ref and context_ref.surface.casefold() == target_ref_casefold:
                kind = self._normalize_entity_type(context_ref.resolved_kind) or self._normalize_entity_type(  # type: ignore[attr-defined]
                    context_ref.resolved_ref.split(":", 1)[0]
                )
                return context_ref.resolved_ref, kind, context_ref.resolved_ref
        return None, None, None

    def _derive_assertion_decay(
        self,
        *,
        event: MemoryEvent,
        candidate: L2AssertionCandidate,
        target_entity_id: str | None,
    ) -> tuple[str, str, float | None]:
        temporal_scope = self._non_empty_text(candidate.temporal_scope)  # type: ignore[attr-defined]
        decay_policy = self._non_empty_text(candidate.decay_policy)  # type: ignore[attr-defined]
        expires_at = candidate.expires_at
        if temporal_scope and decay_policy:
            return temporal_scope, decay_policy, float(expires_at) if expires_at is not None else None

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
        raw_candidates: list[L2AssertionCandidate],
        assertion_scope: str,
    ) -> list[L2AssertionCandidate]:
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
