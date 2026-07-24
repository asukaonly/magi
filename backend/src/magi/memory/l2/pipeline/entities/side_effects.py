"""Entity side-effect helpers for L2Pipeline extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...models import ResolvedEntityMention
from ...storage.utils import normalize_event_ids

if TYPE_CHECKING:
    from ....hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
    from ....l1.event_store import L1EventStore

logger = get_logger(__name__)


class _L2EntitySideEffectHostProtocol(Protocol):
    _l1_store: L1EventStore | None
    _semantic_edge_builder: EntityScopedSemanticBuilder | None


class L2EntitySideEffectMixin:
    """Publish entity linkage side effects after Phase 1 resolution."""

    async def _write_event_entity_links(
        self,
        *,
        event: MemoryEvent,
        batch_event_ids: list[str],
        resolved_mentions: list[ResolvedEntityMention],
    ) -> None:
        host = self._entity_side_effect_host()
        if not resolved_mentions or host._l1_store is None:
            return

        entity_mappings = []
        for mention in resolved_mentions:
            if not mention.resolved_entity_id:
                continue
            scoped_event_ids = normalize_event_ids(mention.evidence_event_ids)
            for event_id in scoped_event_ids:
                entity_mappings.append(
                    (event_id, mention.resolved_entity_id, mention.entity_type, mention.confidence)
                )
        if not entity_mappings:
            return

        try:
            await host._l1_store.write_event_entities(entity_mappings)
        except Exception as exc:
            logger.warning(
                "Failed to write l1_event_entities",
                event_id=event.event_id,
                exc_info=exc,
            )

    async def _build_entity_semantic_edges(
        self,
        *,
        event: MemoryEvent,
        resolved_mentions: list[ResolvedEntityMention],
    ) -> None:
        host = self._entity_side_effect_host()
        if not resolved_mentions or host._semantic_edge_builder is None:
            return

        resolved_entity_ids = list(
            {
                mention.resolved_entity_id
                for mention in resolved_mentions
                if mention.resolved_entity_id and mention.evidence_event_ids
            }
        )
        if not resolved_entity_ids:
            return

        try:
            sem_edge_count = await host._semantic_edge_builder.build_edges_for_event(
                event_id=event.event_id,
                entity_ids=resolved_entity_ids,
                observed_at=float(event.timestamp),
            )
            if sem_edge_count > 0:
                logger.debug(
                    "Entity-scoped semantic edges created",
                    event_id=event.event_id,
                    edge_count=sem_edge_count,
                )
        except Exception as exc:
            logger.warning(
                "Entity-scoped semantic edge building failed",
                event_id=event.event_id,
                exc_info=exc,
            )

    def _entity_side_effect_host(self) -> _L2EntitySideEffectHostProtocol:
        return cast(_L2EntitySideEffectHostProtocol, self)


__all__ = ["L2EntitySideEffectMixin"]
