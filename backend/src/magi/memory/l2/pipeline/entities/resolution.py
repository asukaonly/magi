"""Entity resolution methods for L2Pipeline."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...llm_json_client import L2LLMJsonError
from ...models import (
    L2BatchEntityResolutionItem,
    L2ClaimEvidenceMode,
    L2EntityCandidate,
    L2EntityResolutionMention,
    L2Phase1Entity,
    L2Phase1Result,
    ResolvedEntityMention,
)
from ...ontology import is_vague_entity_reference
from .id_resolution import L2EntityIdResolutionMixin
from ...storage.utils import normalize_event_ids

if TYPE_CHECKING:
    from ...entities.catalog import L2EntityCatalog
    from ...llm_service import L2LLMService

logger = get_logger(__name__)


@dataclass(slots=True)
class _PendingPhase1EntityResolution:
    entity: L2Phase1Entity
    mention_text: str
    normalized_surface: str
    entity_type: str | None
    mention_confidence: float
    resolved_entity_id: str | None = None
    resolved_confidence: float | None = None
    llm_mention_key: str | None = None
    source_event_ids: tuple[str, ...] = ()

    @property
    def cache_key(self) -> tuple[str, str | None]:
        return (self.mention_text.strip().casefold(), self.entity_type)

    @property
    def unresolved(self) -> bool:
        return self.resolved_entity_id is None and self.resolved_confidence is None

    def unresolved_mention_payload(self) -> dict[str, Any]:
        return {
            "mention_text": self.mention_text,
            "canonical_name_hint": self.normalized_surface,
            "alias_signals": self.entity.alias_signals,
        }


class L2EntityResolutionMixin(L2EntityIdResolutionMixin):
    """Mixin providing entity resolution methods for L2Pipeline."""

    # These attributes are provided by L2Pipeline at runtime.
    _entity_catalog: Optional[L2EntityCatalog]
    _llm_service: Optional[L2LLMService]

    # Session-level memo cache: (mention_text_casefold, entity_type) → (entity_id, confidence)
    # Avoids repeated LLM calls for the same mention across events within a pipeline run.
    _entity_resolution_cache: dict[tuple[str, str | None], tuple[str | None, float | None]]

    async def _resolve_phase1_entities(
        self,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
        *,
        evidence_event_ids: list[str],
        evidence_events: list[MemoryEvent] | None = None,
        allowed_entity_types: frozenset[str] | None = None,
        profile_signal_object_refs: set[str] | None = None,
    ) -> list[ResolvedEntityMention]:
        """Register Phase 1 entities in the entity catalog and return resolved mentions.

        Uses a two-pass approach to batch LLM entity resolution calls:
        Pass 1 — alias resolution (fast DB lookups), collect unresolved entities.
        Batch LLM call for all unresolved entities.
        Pass 2 — apply LLM results, finalize catalog records.
        """
        if self._entity_catalog is None:
            return []

        (
            pending,
            llm_batch_items,
            context_only_mentions,
        ) = await self._prepare_phase1_entity_resolution_plan(
            event=event,
            phase1_result=phase1_result,
            evidence_event_ids=evidence_event_ids,
            evidence_events=evidence_events,
            allowed_entity_types=allowed_entity_types,
            profile_signal_object_refs=profile_signal_object_refs,
        )
        llm_results = await self._resolve_phase1_entity_batch(
            llm_batch_items,
            source=event.source,
        )
        if llm_results is None:
            degraded_stages = phase1_result.diagnostics.get("degraded_stages")
            if not isinstance(degraded_stages, list):
                degraded_stages = []
                phase1_result.diagnostics["degraded_stages"] = degraded_stages
            if "entity_resolution" not in degraded_stages:
                degraded_stages.append("entity_resolution")

        resolved_mentions = list(context_only_mentions)
        for pending_item in pending:
            await self._finalize_phase1_entity_resolution(
                pending_item,
                llm_results=llm_results,
            )
            resolved = await self._record_phase1_entity_mention(
                pending_item,
                evidence_events=evidence_events,
                evidence_event_ids=evidence_event_ids,
            )
            if resolved is not None:
                resolved_mentions.append(resolved)
        return resolved_mentions

    async def _prepare_phase1_entity_resolution_plan(
        self,
        *,
        event: MemoryEvent,
        phase1_result: L2Phase1Result,
        evidence_event_ids: list[str],
        evidence_events: list[MemoryEvent] | None,
        allowed_entity_types: frozenset[str] | None,
        profile_signal_object_refs: set[str] | None,
    ) -> tuple[
        list[_PendingPhase1EntityResolution],
        list[L2BatchEntityResolutionItem],
        list[ResolvedEntityMention],
    ]:
        pending: list[_PendingPhase1EntityResolution] = []
        llm_batch_items: list[L2BatchEntityResolutionItem] = []
        context_only_mentions: list[ResolvedEntityMention] = []
        for entity in phase1_result.entities:
            pending_item = self._build_phase1_entity_resolution_candidate(
                entity=entity,
                event=event,
                allowed_entity_types=allowed_entity_types,
                profile_signal_object_refs=profile_signal_object_refs,
            )
            if pending_item is None:
                continue
            pending_item.source_event_ids = tuple(
                self._resolve_entity_mention_event_ids(
                    mention_text=pending_item.mention_text,
                    normalized_surface=pending_item.normalized_surface,
                    evidence_events=evidence_events,
                    fallback_event_ids=evidence_event_ids,
                )
            )
            if not pending_item.source_event_ids:
                context_only_mention = await self._resolve_context_only_existing_entity(
                    pending_item,
                    phase1_result=phase1_result,
                )
                if context_only_mention is not None:
                    context_only_mentions.append(context_only_mention)
                continue
            await self._resolve_phase1_entity_candidate_locally(
                pending_item,
                event=event,
                llm_batch_items=llm_batch_items,
            )
            pending.append(pending_item)
        return pending, llm_batch_items, context_only_mentions

    async def _resolve_context_only_existing_entity(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        phase1_result: L2Phase1Result,
    ) -> ResolvedEntityMention | None:
        proposed_entity_id = str(pending_item.entity.resolved_id or "").strip()
        if not proposed_entity_id or self._entity_catalog is None:
            return None
        entity_refs = {
            pending_item.mention_text.strip().casefold(),
            pending_item.normalized_surface.strip().casefold(),
            proposed_entity_id.casefold(),
        }
        has_grounded_contextual_claim = any(
            claim.evidence_mode is not L2ClaimEvidenceMode.DIRECT
            and str(claim.object_ref or "").strip().casefold() in entity_refs
            for claim in phase1_result.fact_claims
        )
        if not has_grounded_contextual_claim:
            return None
        existing_entities = await self._entity_catalog.find_by_canonical_name(
            pending_item.normalized_surface
        )
        if not any(
            str(item.get("entity_id") or "").strip() == proposed_entity_id
            for item in existing_entities
        ):
            return None
        return ResolvedEntityMention(
            mention_text=pending_item.mention_text,
            normalized_surface=pending_item.normalized_surface,
            entity_type=pending_item.entity_type,
            resolved_entity_id=proposed_entity_id,
            confidence=min(pending_item.mention_confidence, 0.75),
            evidence_event_ids=[],
        )

    def _build_phase1_entity_resolution_candidate(
        self,
        *,
        entity: L2Phase1Entity,
        event: MemoryEvent,
        allowed_entity_types: frozenset[str] | None,
        profile_signal_object_refs: set[str] | None,
    ) -> _PendingPhase1EntityResolution | None:
        if not entity.surface:
            return None
        if str(entity.specificity or "").strip().casefold() != "concrete":
            logger.debug(
                "L2 Phase 1 entity filtered as underspecified",
                mention_text=entity.surface,
                entity_type=entity.entity_type,
                event_id=event.event_id,
            )
            return None
        mention_text = entity.surface
        normalized_surface = entity.normalized_name or mention_text
        entity_type = self._normalize_entity_type(entity.entity_type)  # type: ignore[attr-defined]
        if not self._phase1_entity_passes_filters(
            mention_text=mention_text,
            normalized_surface=normalized_surface,
            entity_type=entity_type,
            event=event,
            allowed_entity_types=allowed_entity_types,
            profile_signal_object_refs=profile_signal_object_refs,
        ):
            return None
        return _PendingPhase1EntityResolution(
            entity=entity,
            mention_text=mention_text,
            normalized_surface=normalized_surface,
            entity_type=entity_type,
            mention_confidence=entity.confidence,
        )

    def _phase1_entity_passes_filters(
        self,
        *,
        mention_text: str,
        normalized_surface: str,
        entity_type: str | None,
        event: MemoryEvent,
        allowed_entity_types: frozenset[str] | None,
        profile_signal_object_refs: set[str] | None,
    ) -> bool:
        if is_vague_entity_reference(mention_text) or is_vague_entity_reference(normalized_surface):
            logger.debug(
                "L2 Phase 1 entity filtered as vague reference",
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                event_id=event.event_id,
            )
            return False

        normalized_profile_value = self._normalize_profile_signal_value(normalized_surface)  # type: ignore[attr-defined]
        normalized_mention_value = self._normalize_profile_signal_value(mention_text)  # type: ignore[attr-defined]
        if profile_signal_object_refs and (
            normalized_profile_value in profile_signal_object_refs
            or normalized_mention_value in profile_signal_object_refs
        ):
            logger.debug(
                "L2 Phase 1 entity filtered as profile signal value",
                mention_text=mention_text,
                entity_type=entity_type,
                event_id=event.event_id,
            )
            return False

        if allowed_entity_types and entity_type not in allowed_entity_types:
            logger.debug(
                "L2 Phase 1 entity filtered by profile",
                mention_text=mention_text,
                entity_type=entity_type,
                event_id=event.event_id,
            )
            return False

        if not self._is_quality_entity_name(normalized_surface):
            logger.debug(
                "L2 Phase 1 entity filtered by name quality",
                mention_text=mention_text,
                entity_type=entity_type,
                event_id=event.event_id,
            )
            return False

        return True

    async def _resolve_phase1_entity_candidate_locally(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        event: MemoryEvent,
        llm_batch_items: list[L2BatchEntityResolutionItem],
    ) -> None:
        if pending_item.entity.resolved_id:
            pending_item.resolved_entity_id = await self._prefer_existing_same_name_entity(
                proposed_entity_id=pending_item.entity.resolved_id,
                canonical_name=pending_item.normalized_surface,
                entity_type=pending_item.entity_type,
                mention_text=pending_item.mention_text,
                confidence=pending_item.mention_confidence,
                source_event_ids=pending_item.source_event_ids,
            )
            pending_item.resolved_confidence = pending_item.entity.confidence
            return

        cache = self._phase1_resolution_cache()
        if cache is not None and pending_item.cache_key in cache:
            cached_id, cached_confidence = cache[pending_item.cache_key]
            logger.debug(
                "L2 entity resolution cache hit",
                mention_text=pending_item.mention_text,
                entity_type=pending_item.entity_type,
                cached_entity_id=cached_id,
            )
            pending_item.resolved_entity_id = cached_id
            pending_item.resolved_confidence = cached_confidence
            return

        alias_result = await self._try_alias_resolution(
            pending_item.mention_text,
            pending_item.entity_type,
        )
        if alias_result is not None:
            pending_item.resolved_entity_id, pending_item.resolved_confidence = alias_result
            if cache is not None:
                cache[pending_item.cache_key] = alias_result
            return

        await self._queue_phase1_entity_llm_resolution(
            pending_item,
            event=event,
            llm_batch_items=llm_batch_items,
        )

    async def _queue_phase1_entity_llm_resolution(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        event: MemoryEvent,
        llm_batch_items: list[L2BatchEntityResolutionItem],
    ) -> None:
        if self._llm_service is None or not pending_item.entity_type:
            return

        assert self._entity_catalog is not None
        candidate_entities = await self._entity_catalog.find_resolution_candidates(
            pending_item.mention_text,
            entity_type=pending_item.entity_type,
            limit=20,
        )
        if not candidate_entities:
            return

        mention_key = f"{len(llm_batch_items)}"
        pending_item.llm_mention_key = mention_key
        llm_batch_items.append(
            L2BatchEntityResolutionItem(
                mention_key=mention_key,
                mention=L2EntityResolutionMention(
                    mention_text=pending_item.mention_text,
                    entity_type=pending_item.entity_type,
                    context_text=event.content,
                ),
                candidate_entities=[
                    L2EntityCandidate.from_dict(item) for item in candidate_entities
                ],
            )
        )

    async def _resolve_phase1_entity_batch(
        self,
        llm_batch_items: list[L2BatchEntityResolutionItem],
        *,
        source: str | None = None,
    ) -> dict[str, Any] | None:
        if not llm_batch_items or self._llm_service is None:
            return {}
        try:
            return await self._llm_service.resolve_entities_batch(
                items=llm_batch_items,
                source=source,
            )
        except L2LLMJsonError as exc:
            logger.warning(
                "L2 Phase 1 entity resolution degraded",
                source=source,
                mention_count=len(llm_batch_items),
                error_type=type(exc).__name__,
            )
            return None

    async def _finalize_phase1_entity_resolution(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        llm_results: dict[str, Any] | None,
    ) -> None:
        if pending_item.llm_mention_key is not None:
            if llm_results is None:
                pending_item.resolved_entity_id = None
                pending_item.resolved_confidence = 0.0
                return
            await self._apply_phase1_llm_resolution(
                pending_item,
                llm_results=llm_results,
            )
            self._cache_phase1_resolution(pending_item)
            return

        if pending_item.unresolved:
            await self._finalize_unresolved_phase1_entity(pending_item)
            self._cache_phase1_resolution(pending_item)

    async def _apply_phase1_llm_resolution(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        llm_results: dict[str, Any],
    ) -> None:
        llm_resolution = llm_results.get(pending_item.llm_mention_key)
        if (
            llm_resolution is not None
            and llm_resolution.decision == "match"
            and llm_resolution.matched_entity_id
        ):
            pending_item.resolved_entity_id = str(llm_resolution.matched_entity_id)
            pending_item.resolved_confidence = float(
                llm_resolution.confidence or pending_item.mention_confidence
            )
            return

        await self._finalize_unresolved_phase1_entity(pending_item)

    async def _finalize_unresolved_phase1_entity(
        self,
        pending_item: _PendingPhase1EntityResolution,
    ) -> None:
        (
            pending_item.resolved_entity_id,
            pending_item.resolved_confidence,
        ) = await self._finalize_unresolved_entity(
            mention=pending_item.unresolved_mention_payload(),
            entity_type=pending_item.entity_type,
            mention_text=pending_item.mention_text,
            mention_confidence=pending_item.mention_confidence,
            source_event_ids=pending_item.source_event_ids,
        )

    async def _record_phase1_entity_mention(
        self,
        pending_item: _PendingPhase1EntityResolution,
        *,
        evidence_events: list[MemoryEvent] | None,
        evidence_event_ids: list[str],
    ) -> ResolvedEntityMention | None:
        assert self._entity_catalog is not None

        allowed_event_ids = await self._entity_catalog.filter_projection_source_event_ids(
            target_entity_id=pending_item.resolved_entity_id,
            normalized_surface=pending_item.normalized_surface,
            entity_type=pending_item.entity_type,
            event_ids=pending_item.source_event_ids,
        )
        if not allowed_event_ids:
            return None
        pending_item.source_event_ids = allowed_event_ids

        if pending_item.resolved_entity_id:
            pending_item.entity.resolved_id = pending_item.resolved_entity_id
            await self._entity_catalog.upsert_entity(
                canonical_name=pending_item.normalized_surface,
                entity_type=pending_item.entity_type,
                entity_id=pending_item.resolved_entity_id,
                source_event_ids=pending_item.source_event_ids,
            )
            await self._entity_catalog.add_alias(
                entity_id=pending_item.resolved_entity_id,
                alias_text=pending_item.mention_text,
                confidence=float(pending_item.resolved_confidence or 0.5),
                source_event_ids=pending_item.source_event_ids,
            )

        mention_event_ids = list(allowed_event_ids)
        await self._entity_catalog.record_mention(
            mention_text=pending_item.mention_text,
            normalized_surface=pending_item.normalized_surface,
            entity_type=pending_item.entity_type,
            evidence_event_ids=mention_event_ids,
            evidence_text=pending_item.mention_text,
            resolved_entity_id=pending_item.resolved_entity_id,
            confidence=pending_item.resolved_confidence,
        )
        return ResolvedEntityMention(
            mention_text=pending_item.mention_text,
            normalized_surface=pending_item.normalized_surface,
            entity_type=pending_item.entity_type,
            resolved_entity_id=pending_item.resolved_entity_id,
            confidence=pending_item.resolved_confidence,
            evidence_event_ids=mention_event_ids,
        )

    def _phase1_resolution_cache(
        self,
    ) -> dict[tuple[str, str | None], tuple[str | None, float | None]] | None:
        return getattr(self, "_entity_resolution_cache", None)

    def _cache_phase1_resolution(
        self,
        pending_item: _PendingPhase1EntityResolution,
    ) -> None:
        cache = self._phase1_resolution_cache()
        if cache is not None:
            cache[pending_item.cache_key] = (
                pending_item.resolved_entity_id,
                pending_item.resolved_confidence,
            )

    def _resolve_entity_mention_event_ids(
        self,
        *,
        mention_text: str,
        normalized_surface: str,
        evidence_events: list[MemoryEvent] | None,
        fallback_event_ids: list[str],
    ) -> list[str]:
        matched_event_ids: list[str] = []
        mention_candidates = {
            unicodedata.normalize("NFKC", str(text)).strip().casefold()
            for text in (mention_text, normalized_surface)
            if str(text or "").strip()
        }
        for evidence_event in evidence_events or []:
            content = unicodedata.normalize(
                "NFKC",
                str(getattr(evidence_event, "content", "") or ""),
            ).casefold()
            if any(candidate in content for candidate in mention_candidates):
                event_id = str(getattr(evidence_event, "event_id", "") or "").strip()
                if event_id:
                    matched_event_ids.append(event_id)
        if matched_event_ids:
            return normalize_event_ids(matched_event_ids)
        normalized_fallback_ids = normalize_event_ids(fallback_event_ids)
        if evidence_events is None:
            return normalized_fallback_ids
        return []

    async def _resolve_mentions(
        self,
        event: MemoryEvent,
        mentions: list[dict[str, Any]],
        *,
        evidence_event_ids: list[str] | None = None,
    ) -> list[ResolvedEntityMention]:
        if self._entity_catalog is None:
            return []

        resolved_mentions: list[ResolvedEntityMention] = []
        for mention in mentions:
            if not isinstance(mention, dict):
                continue

            mention_text = str(mention.get("mention_text", "")).strip()
            if not mention_text:
                continue
            normalized_surface = str(mention.get("normalized_surface") or mention_text).strip()
            entity_type = self._normalize_entity_type(mention.get("entity_type"))  # type: ignore[attr-defined]
            if is_vague_entity_reference(mention_text) or is_vague_entity_reference(
                normalized_surface
            ):
                logger.debug(
                    "L2 mention filtered as vague reference",
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
            evidence_text = self._non_empty_text(mention.get("evidence_text")) or event.content  # type: ignore[attr-defined]
            mention_confidence = float(mention.get("confidence", 0.0) or 0.0)

            resolved_entity_id, resolved_confidence = await self._resolve_entity_id(
                mention=mention,
                entity_type=entity_type,
                mention_text=mention_text,
                mention_confidence=mention_confidence,
                event=event,
                source_event_ids=normalize_event_ids(evidence_event_ids or [event.event_id]),
            )

            allowed_event_ids = await self._entity_catalog.filter_projection_source_event_ids(
                target_entity_id=resolved_entity_id,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                event_ids=normalize_event_ids(evidence_event_ids or [event.event_id]),
            )
            if not allowed_event_ids:
                continue

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=list(allowed_event_ids),
                evidence_text=evidence_text,
                resolved_entity_id=resolved_entity_id,
                confidence=resolved_confidence,
            )
            resolved_mentions.append(
                ResolvedEntityMention(
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    resolved_entity_id=resolved_entity_id,
                    confidence=resolved_confidence,
                    evidence_event_ids=list(allowed_event_ids),
                )
            )
        return resolved_mentions


__all__ = ["L2EntityResolutionMixin"]
