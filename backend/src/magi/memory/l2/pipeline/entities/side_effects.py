"""Entity side-effect helpers for L2Pipeline extraction."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, cast

from .....core.logger import get_logger
from ....event_contracts import MemoryEvent
from ...models import L2ProjectionLease, ResolvedEntityMention
from ...projection.errors import ProjectionAttemptFencedError
from ...storage.utils import normalize_event_ids

if TYPE_CHECKING:
    from ....hybrid_retrieval.entity_semantic_builder import EntityScopedSemanticBuilder
    from ....l1.event_store import L1EventStore
    from ...store import L2CognitionStore

logger = get_logger(__name__)


class _L2EntitySideEffectHostProtocol(Protocol):
    _cognition_store: L2CognitionStore | None
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
        projection_leases: Sequence[L2ProjectionLease] = (),
    ) -> None:
        host = self._entity_side_effect_host()
        entity_mappings: list[tuple[str, str, str | None, float | None]] = []
        for mention in resolved_mentions:
            if not mention.resolved_entity_id:
                continue
            scoped_event_ids = normalize_event_ids(mention.evidence_event_ids)
            for event_id in scoped_event_ids:
                entity_mappings.append(
                    (event_id, mention.resolved_entity_id, mention.entity_type, mention.confidence)
                )

        if not projection_leases:
            if not entity_mappings or host._l1_store is None:
                return
            try:
                await host._l1_store.write_event_entities(entity_mappings)
            except Exception as exc:
                logger.warning(
                    "Failed to write direct L1 event entity links",
                    event_id=event.event_id,
                    exc_info=exc,
                )
            return

        cognition_store = host._cognition_store
        if cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable")
        lease_event_ids = {lease.event_id for lease in projection_leases}
        if set(batch_event_ids) != lease_event_ids:
            raise ValueError("batch event IDs must match projection leases")
        desired_links_by_event: dict[
            str,
            list[tuple[str, str | None, float | None]],
        ] = {event_id: [] for event_id in sorted(lease_event_ids)}
        for event_id, entity_id, entity_type, confidence in entity_mappings:
            if event_id not in desired_links_by_event:
                continue
            desired_links_by_event[event_id].append((entity_id, entity_type, confidence))
        await cognition_store.stage_event_entity_link_projections(
            desired_links_by_event=desired_links_by_event,
            projection_leases=projection_leases,
        )

    async def _drain_event_entity_link_outbox(
        self,
        *,
        raise_on_error: bool = False,
    ) -> int:
        """Apply pending L2 desired sets to L1 and CAS-ack each revision."""

        host = self._entity_side_effect_host()
        cognition_store = host._cognition_store
        if cognition_store is None or host._l1_store is None:
            return 0
        ready_batches = await cognition_store.prepare_event_entity_link_outbox()
        acknowledged = 0
        for batch in ready_batches:
            try:
                accepted = await host._l1_store.replace_projected_event_entities_batch(
                    projections=[
                        (
                            item.event_id,
                            item.revision,
                            item.lease_token,
                            item.attempt_count,
                            item.clear_generation,
                            list(item.desired_links),
                        )
                        for item in batch.items
                    ],
                )
                if not accepted:
                    if raise_on_error:
                        raise RuntimeError("L1 entity-link projection batch was not accepted")
                    logger.warning(
                        "L1 entity-link projection batch was not accepted",
                        batch_key=batch.batch_key,
                    )
                    continue
                if await cognition_store.acknowledge_event_entity_link_projection_batch(batch):
                    acknowledged += len(batch.items)
                elif raise_on_error:
                    raise RuntimeError("L2 entity-link projection batch was not acknowledged")
            except Exception as exc:
                if raise_on_error:
                    raise
                logger.warning(
                    "Failed to reconcile L1 event entity-link batch",
                    batch_key=batch.batch_key,
                    exc_info=exc,
                )
        return acknowledged

    async def _replace_event_entity_links_with_empty(
        self,
        projection_leases: Sequence[L2ProjectionLease],
    ) -> None:
        """Clear prior L2 links for a successful projection with no mentions."""

        if not projection_leases:
            return
        host = self._entity_side_effect_host()
        cognition_store = host._cognition_store
        if cognition_store is None:
            raise RuntimeError("L2 cognition store is unavailable")
        await self._drain_event_entity_link_outbox()
        await cognition_store.stage_event_entity_link_projections(
            desired_links_by_event={lease.event_id: [] for lease in projection_leases},
            projection_leases=projection_leases,
        )

    async def _build_entity_semantic_edges(
        self,
        *,
        event: MemoryEvent,
        resolved_mentions: list[ResolvedEntityMention],
        projection_leases: list[L2ProjectionLease],
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
                projection_leases=projection_leases,
            )
            if sem_edge_count > 0:
                logger.debug(
                    "Entity-scoped semantic edges created",
                    event_id=event.event_id,
                    edge_count=sem_edge_count,
                )
        except ProjectionAttemptFencedError:
            raise
        except Exception as exc:
            logger.warning(
                "Entity-scoped semantic edge building failed",
                event_id=event.event_id,
                exc_info=exc,
            )

    def _entity_side_effect_host(self) -> _L2EntitySideEffectHostProtocol:
        return cast(_L2EntitySideEffectHostProtocol, self)


__all__ = ["L2EntitySideEffectMixin"]
