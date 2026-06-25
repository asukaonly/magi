"""Entity resolution methods for L2Pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...models import (
    L2BatchEntityResolutionItem,
    L2EntityCandidate,
    L2EntityResolutionMention,
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

        # ── Pass 1: filter, alias-resolve, collect LLM candidates ──
        # Each item: (entity, mention_text, normalized_surface, entity_type, confidence,
        #             resolved_id, resolved_confidence, needs_llm)
        pending: list[tuple[Any, ...]] = []
        llm_batch_items: list[L2BatchEntityResolutionItem] = []

        for entity in phase1_result.entities:
            if not entity.surface:
                continue
            mention_text = entity.surface
            normalized_surface = entity.normalized_name or mention_text
            entity_type = self._normalize_entity_type(entity.entity_type)  # type: ignore[attr-defined]
            if is_vague_entity_reference(mention_text) or is_vague_entity_reference(normalized_surface):
                logger.debug(
                    "L2 Phase 1 entity filtered as vague reference",
                    mention_text=mention_text,
                    normalized_surface=normalized_surface,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
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
                continue
            if allowed_entity_types and entity_type not in allowed_entity_types:
                logger.debug(
                    "L2 Phase 1 entity filtered by profile",
                    mention_text=mention_text,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
            if not self._is_quality_entity_name(normalized_surface):
                logger.debug(
                    "L2 Phase 1 entity filtered by name quality",
                    mention_text=mention_text,
                    entity_type=entity_type,
                    event_id=event.event_id,
                )
                continue
            mention_confidence = entity.confidence

            # If Phase 1 already resolved the entity to an existing ID, use it
            if entity.resolved_id:
                resolved_entity_id = await self._prefer_existing_same_name_entity(
                    proposed_entity_id=entity.resolved_id,
                    canonical_name=normalized_surface,
                    entity_type=entity_type,
                    mention_text=mention_text,
                    confidence=mention_confidence,
                )
                pending.append(
                    (
                        entity,
                        mention_text,
                        normalized_surface,
                        entity_type,
                        mention_confidence,
                        resolved_entity_id,
                        entity.confidence,
                        False,
                    )
                )
                continue

            # Check session-level memo cache
            cache_key = (mention_text.strip().casefold(), entity_type)
            cache = getattr(self, "_entity_resolution_cache", None)
            if cache is not None and cache_key in cache:
                cached_id, cached_conf = cache[cache_key]
                logger.debug(
                    "L2 entity resolution cache hit",
                    mention_text=mention_text,
                    entity_type=entity_type,
                    cached_entity_id=cached_id,
                )
                pending.append(
                    (
                        entity,
                        mention_text,
                        normalized_surface,
                        entity_type,
                        mention_confidence,
                        cached_id,
                        cached_conf,
                        False,
                    )
                )
                continue

            # Try alias resolution (fast DB lookup)
            alias_result = await self._try_alias_resolution(mention_text, entity_type)
            if alias_result is not None:
                resolved_id, resolved_conf = alias_result
                if cache is not None:
                    cache[cache_key] = alias_result
                pending.append(
                    (
                        entity,
                        mention_text,
                        normalized_surface,
                        entity_type,
                        mention_confidence,
                        resolved_id,
                        resolved_conf,
                        False,
                    )
                )
                continue

            # Needs LLM resolution — collect candidates
            if self._llm_service is not None and entity_type:
                candidate_entities = await self._entity_catalog.find_resolution_candidates(
                    mention_text,
                    entity_type=entity_type,
                    limit=20,
                )
                if candidate_entities:
                    mention_key = f"{len(llm_batch_items)}"
                    llm_batch_items.append(
                        L2BatchEntityResolutionItem(
                            mention_key=mention_key,
                            mention=L2EntityResolutionMention(
                                mention_text=mention_text,
                                entity_type=entity_type,
                                context_text=event.content,
                            ),
                            candidate_entities=[
                                L2EntityCandidate.from_dict(item) for item in candidate_entities
                            ],
                        )
                    )
                    pending.append(
                        (
                            entity,
                            mention_text,
                            normalized_surface,
                            entity_type,
                            mention_confidence,
                            None,
                            None,
                            True,
                        )
                    )
                    continue

            # No LLM needed (no candidates or no llm_service)
            pending.append(
                (
                    entity,
                    mention_text,
                    normalized_surface,
                    entity_type,
                    mention_confidence,
                    None,
                    None,
                    False,
                )
            )

        # ── Batch LLM resolution ──
        llm_results: dict[str, Any] = {}
        if llm_batch_items and self._llm_service is not None:
            llm_results = await self._llm_service.resolve_entities_batch(items=llm_batch_items)

        # ── Pass 2: apply LLM results, finalize catalog, build output ──
        resolved_mentions: list[ResolvedEntityMention] = []
        llm_item_idx = 0  # tracks which llm_batch_item corresponds to needs_llm entries
        for (
            entity,
            mention_text,
            normalized_surface,
            entity_type,
            mention_confidence,
            resolved_entity_id,
            resolved_confidence,
            needs_llm,
        ) in pending:
            if needs_llm:
                mention_key = f"{llm_item_idx}"
                llm_item_idx += 1
                llm_resolution = llm_results.get(mention_key)
                if (
                    llm_resolution is not None
                    and llm_resolution.decision == "match"
                    and llm_resolution.matched_entity_id
                ):
                    resolved_entity_id = str(llm_resolution.matched_entity_id)
                    resolved_confidence = float(llm_resolution.confidence or mention_confidence)
                else:
                    # Fall through to same-name dedup / creation
                    (
                        resolved_entity_id,
                        resolved_confidence,
                    ) = await self._finalize_unresolved_entity(
                        mention={
                            "mention_text": mention_text,
                            "canonical_name_hint": normalized_surface,
                            "alias_signals": entity.alias_signals,
                        },
                        entity_type=entity_type,
                        mention_text=mention_text,
                        mention_confidence=mention_confidence,
                    )
                # Update cache
                cache_key = (mention_text.strip().casefold(), entity_type)
                cache = getattr(self, "_entity_resolution_cache", None)
                if cache is not None:
                    cache[cache_key] = (resolved_entity_id, resolved_confidence)
            elif resolved_entity_id is None and resolved_confidence is None:
                # Was not resolved by alias nor Phase 1 and didn't go through LLM
                # (no candidates or no llm_service) — try same-name dedup / creation
                resolved_entity_id, resolved_confidence = await self._finalize_unresolved_entity(
                    mention={
                        "mention_text": mention_text,
                        "canonical_name_hint": normalized_surface,
                        "alias_signals": entity.alias_signals,
                    },
                    entity_type=entity_type,
                    mention_text=mention_text,
                    mention_confidence=mention_confidence,
                )
                cache_key = (mention_text.strip().casefold(), entity_type)
                cache = getattr(self, "_entity_resolution_cache", None)
                if cache is not None:
                    cache[cache_key] = (resolved_entity_id, resolved_confidence)

            # Ensure the entity exists in the catalog before recording the mention (FK constraint)
            if resolved_entity_id:
                entity.resolved_id = resolved_entity_id
                await self._entity_catalog.upsert_entity(
                    canonical_name=normalized_surface,
                    entity_type=entity_type,
                    entity_id=resolved_entity_id,
                )

            mention_event_ids = self._resolve_entity_mention_event_ids(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                evidence_events=evidence_events,
                fallback_event_ids=evidence_event_ids,
            )
            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=mention_event_ids,
                evidence_text=mention_text,
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
                    evidence_event_ids=mention_event_ids,
                )
            )
        return resolved_mentions

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
            text.strip()
            for text in (mention_text, normalized_surface)
            if str(text or "").strip()
        }
        for evidence_event in evidence_events or []:
            content = str(getattr(evidence_event, "content", "") or "")
            if any(candidate in content for candidate in mention_candidates):
                event_id = str(getattr(evidence_event, "event_id", "") or "").strip()
                if event_id:
                    matched_event_ids.append(event_id)
        return normalize_event_ids(matched_event_ids or fallback_event_ids)

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
            if is_vague_entity_reference(mention_text) or is_vague_entity_reference(normalized_surface):
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
            )

            await self._entity_catalog.record_mention(
                mention_text=mention_text,
                normalized_surface=normalized_surface,
                entity_type=entity_type,
                evidence_event_ids=normalize_event_ids(evidence_event_ids or [event.event_id]),
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
                    evidence_event_ids=normalize_event_ids(evidence_event_ids or [event.event_id]),
                )
            )
        return resolved_mentions


__all__ = ["L2EntityResolutionMixin"]
