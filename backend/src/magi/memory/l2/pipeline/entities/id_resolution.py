"""Single-mention entity ID resolution helpers for L2Pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...entities.identity import CONCEPT_ENTITY_TYPES, scoped_entity_id, normalized_entity_name
from ...models import L2EntityCandidate, L2EntityResolutionMention, L2ProjectionLease
from .helpers import L2EntityResolutionHelperMixin

if TYPE_CHECKING:
    from ...entities.catalog import L2EntityCatalog
    from ...llm_service import L2LLMService

logger = get_logger(__name__)


class L2EntityIdResolutionMixin(L2EntityResolutionHelperMixin):
    """Resolve one mention to an entity id and finalize catalog records."""

    _entity_catalog: Optional[L2EntityCatalog]
    _llm_service: Optional[L2LLMService]
    _entity_resolution_cache: dict[tuple[str, str | None], tuple[str | None, float | None]]

    async def _resolve_entity_id(
        self,
        *,
        mention: dict[str, Any],
        entity_type: Optional[str],
        mention_text: str,
        mention_confidence: float,
        event: MemoryEvent,
        source_event_ids: Iterable[str],
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> tuple[Optional[str], Optional[float]]:
        if self._entity_catalog is None:
            return (None, None)

        cache_key = (mention_text.strip().casefold() if entity_type in CONCEPT_ENTITY_TYPES else f"{event.event_id}:{mention_text.strip().casefold()}", entity_type)
        cache: dict[tuple[str, str | None], tuple[str | None, float | None]] | None = getattr(
            self, "_entity_resolution_cache", None
        )
        if cache is not None and cache_key in cache:
            cached = cache[cache_key]
            logger.debug(
                "L2 entity resolution cache hit",
                mention_text=mention_text,
                entity_type=entity_type,
                cached_entity_id=cached[0],
            )
            return cached

        result = await self._resolve_entity_id_uncached(
            mention=mention,
            entity_type=entity_type,
            mention_text=mention_text,
            mention_confidence=mention_confidence,
            event=event,
            source_event_ids=source_event_ids,
            projection_leases=projection_leases,
        )

        if cache is not None:
            cache[cache_key] = result
        return result

    async def _resolve_entity_id_uncached(
        self,
        *,
        mention: dict[str, Any],
        entity_type: Optional[str],
        mention_text: str,
        mention_confidence: float,
        event: MemoryEvent,
        source_event_ids: Iterable[str],
        projection_leases: Iterable[L2ProjectionLease],
    ) -> tuple[Optional[str], Optional[float]]:
        assert self._entity_catalog is not None

        alias_result = await self._try_alias_resolution(mention_text, entity_type)
        if alias_result is not None:
            return alias_result

        if self._llm_service is not None and entity_type:
            candidate_entities = await self._entity_catalog.find_resolution_candidates(
                mention_text,
                entity_type=entity_type,
                limit=20,
            )
            if candidate_entities:
                llm_resolution = await self._llm_service.resolve_entity(
                    mention=L2EntityResolutionMention(
                        mention_text=mention_text,
                        entity_type=entity_type,
                        context_text=event.content,
                    ),
                    candidate_entities=[
                        L2EntityCandidate.from_dict(item) for item in candidate_entities
                    ],
                    source=event.source,
                )
                if entity_type in CONCEPT_ENTITY_TYPES and llm_resolution.decision == "match" and llm_resolution.matched_entity_id:
                    return (
                        str(llm_resolution.matched_entity_id),
                        float(llm_resolution.confidence or mention_confidence),
                    )

        return await self._finalize_unresolved_entity(
            mention=mention,
            entity_type=entity_type,
            mention_text=mention_text,
            mention_confidence=mention_confidence,
            source_event_ids=source_event_ids,
            projection_leases=projection_leases,
        )

    async def _try_alias_resolution(
        self,
        mention_text: str,
        entity_type: Optional[str],
    ) -> tuple[str, float] | None:
        """Try alias-based resolution. Returns (entity_id, confidence) or None."""
        assert self._entity_catalog is not None

        if entity_type not in CONCEPT_ENTITY_TYPES:
            return None

        alias_resolution = await self._entity_catalog.resolve_alias(
            mention_text,
            entity_type=entity_type,
        )
        if alias_resolution.get("decision") == "match":
            return (
                str(alias_resolution["entity_id"]),
                float(alias_resolution["matched_confidence"]),
            )

        if entity_type:
            cross_type_resolution = await self._entity_catalog.resolve_alias(
                mention_text,
                entity_type=None,
            )
            if cross_type_resolution.get("decision") == "match":
                matched_id = str(cross_type_resolution["entity_id"])
                matched_type = matched_id.split(":", 1)[0] if ":" in matched_id else ""
                if self._are_types_mergeable(entity_type, matched_type):
                    logger.debug(
                        "L2 cross-type entity resolved",
                        mention_text=mention_text,
                        requested_type=entity_type,
                        matched_type=matched_type,
                        matched_entity_id=matched_id,
                    )
                    return (matched_id, float(cross_type_resolution["matched_confidence"]))

        return None

    async def _prefer_existing_same_name_entity(
        self,
        *,
        proposed_entity_id: str | None,
        canonical_name: str,
        entity_type: str | None,
        mention_text: str,
        confidence: float,
        source_event_ids: Iterable[str],
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> str | None:
        """Preserve an explicitly resolved identity; a shared label is not a merge key."""
        return proposed_entity_id

    async def _finalize_unresolved_entity(
        self,
        *,
        mention: dict[str, Any],
        entity_type: Optional[str],
        mention_text: str,
        mention_confidence: float,
        source_event_ids: Iterable[str],
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> tuple[Optional[str], Optional[float]]:
        """Deduplicate by canonical name or create a new high-confidence entity."""
        assert self._entity_catalog is not None

        canonical_name = self._non_empty_text(mention.get("canonical_name_hint")) or mention_text  # type: ignore[attr-defined]
        if not entity_type or mention_confidence < 0.9:
            return (None, mention_confidence if mention_confidence > 0.0 else None)

        existing_by_name = await self._entity_catalog.find_by_canonical_name(canonical_name)
        if existing_by_name and entity_type in CONCEPT_ENTITY_TYPES:
            for existing in existing_by_name:
                existing_type = str(existing.get("entity_type", ""))
                if existing_type == entity_type or self._are_types_mergeable(
                    entity_type, existing_type
                ):
                    matched_id = str(existing["entity_id"])
                    logger.debug(
                        "L2 entity dedup: reusing existing same-name entity",
                        mention_text=mention_text,
                        canonical_name=canonical_name,
                        requested_type=entity_type,
                        existing_type=existing_type,
                        entity_id=matched_id,
                    )
                    await self._entity_catalog.add_alias(
                        entity_id=matched_id,
                        alias_text=mention_text,
                        confidence=min(max(mention_confidence, 0.9), 0.99),
                        source_event_ids=source_event_ids,
                        projection_leases=projection_leases,
                    )
                    return (matched_id, mention_confidence)

        entity_id = self._build_canonical_entity_id(  # type: ignore[attr-defined]
            entity_type=entity_type, canonical_name=canonical_name
        )
        if entity_type not in CONCEPT_ENTITY_TYPES:
            entity_id = scoped_entity_id(entity_type, "unresolved_mention", ":".join(sorted(source_event_ids)) + ":" + normalized_entity_name(canonical_name))
        await self._entity_catalog.upsert_entity(
            entity_id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            source_event_ids=source_event_ids,
            projection_leases=projection_leases,
        )
        await self._entity_catalog.add_alias(
            entity_id=entity_id,
            alias_text=mention_text,
            confidence=min(max(mention_confidence, 0.9), 0.99),
            source_event_ids=source_event_ids,
            projection_leases=projection_leases,
        )
        for alias in mention.get("alias_signals", []):
            alias_text = self._non_empty_text(alias)  # type: ignore[attr-defined]
            if not alias_text:
                continue
            if not self._is_valid_alias(alias_text, canonical_name, entity_type):
                logger.debug(
                    "L2 alias rejected by validation",
                    alias_text=alias_text,
                    canonical_name=canonical_name,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
                continue
            await self._entity_catalog.add_alias(
                entity_id=entity_id,
                alias_text=alias_text,
                confidence=min(max(mention_confidence, 0.85), 0.95),
                source_event_ids=source_event_ids,
                projection_leases=projection_leases,
            )
        return (entity_id, mention_confidence)


__all__ = ["L2EntityIdResolutionMixin"]
