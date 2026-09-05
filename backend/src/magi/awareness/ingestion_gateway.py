"""Source ingestion publisher.

Builds a SourceEventEmitted payload, commits it to L1 memory, then publishes the
committed event for downstream timeline, graph, and source-state projections.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from ulid import ULID

from ..core.logger import get_logger
from ..events.events import Event, EventTypes
from ..events.domain_payloads import SourceEventEmitted, TaskContext
from ..memory.source_ingestion import (
    SourceCommitOutcome,
    SourceCommitReceipt,
    SourceIngestionBoundary,
)
from ..identity import canonicalize_user_id as _canonicalize_user_id
from ..identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from .source_base import Source
from .source_output import SourceOutput, SourceOutputMetadata
from .source_projection import build_source_projection

logger = get_logger(__name__)


class SourceMemoryCommitter(Protocol):
    """Memory-owned port that proves the terminal L1 outcome of a source event."""

    async def capture_ingestion_boundary(self) -> SourceIngestionBoundary: ...

    async def commit(
        self,
        event: Event,
        *,
        expected_epoch: int,
        clear_generation: int,
        clear_cutoff_at: float,
        allow_pre_clear_events: bool,
    ) -> SourceCommitReceipt: ...


@dataclass(slots=True)
class SourceIngestionResult:
    """Outcome of an authoritative source-memory commit."""

    event_id: str
    ingested: bool = True
    stats: dict[str, Any] = field(default_factory=dict)


class SourceIngestionGateway:
    """Commit source events to memory before publishing derived projections."""

    def __init__(self, *, event_bus, memory_committer: SourceMemoryCommitter) -> None:
        self._event_bus = event_bus
        self._memory_committer = memory_committer

    async def capture_ingestion_boundary(self) -> SourceIngestionBoundary:
        """Capture the clear state that one source batch must retain."""

        return await self._memory_committer.capture_ingestion_boundary()

    async def ingest(
        self,
        source: Source,
        output: SourceOutput,
        metadata: SourceOutputMetadata | None = None,
        *,
        allowed_edge_whitelist: list[str] | None = None,
        boundary: SourceIngestionBoundary | None = None,
        allow_pre_clear_events: bool = False,
        host_idempotency_key: str | None = None,
    ) -> SourceIngestionResult:
        captured_boundary = boundary or await self.capture_ingestion_boundary()
        event_id = str(ULID())
        payload = self._build_source_event_payload(
            source=source,
            output=output,
            metadata=metadata,
            allowed_edge_whitelist=allowed_edge_whitelist,
        )
        if host_idempotency_key is not None:
            payload = replace(payload, idempotency_key=host_idempotency_key)
        event = Event(
            type=EventTypes.SOURCE_EVENT_EMITTED,
            data=payload,
            event_id=event_id,
            source="source_ingestion_gateway",
        )
        receipt = await self._memory_committer.commit(
            event,
            expected_epoch=captured_boundary.expected_epoch,
            clear_generation=captured_boundary.clear_generation,
            clear_cutoff_at=captured_boundary.clear_cutoff_at,
            allow_pre_clear_events=allow_pre_clear_events,
        )
        committed_event = replace(event, event_id=receipt.event_id)
        projection_skipped = receipt.outcome is SourceCommitOutcome.GOVERNED_SKIP
        projection_published = (
            False
            if projection_skipped
            else await self._publish_source_event(
                event=committed_event,
                source_id=source.source_id,
            )
        )
        stats: dict[str, Any] = {
            "memory_outcome": receipt.outcome.value,
            "projection_published": projection_published,
            "projection_skipped": projection_skipped,
        }
        if receipt.skip_reason:
            stats["skip_reason"] = receipt.skip_reason
        return SourceIngestionResult(
            event_id=receipt.event_id,
            ingested=True,
            stats=stats,
        )

    def _build_source_event_payload(
        self,
        *,
        source: Source,
        output: SourceOutput,
        metadata: SourceOutputMetadata | None,
        allowed_edge_whitelist: list[str] | None,
    ) -> SourceEventEmitted:
        owner_user_id = self._resolve_memory_owner_user_id(output)
        projection = build_source_projection(source, output, metadata)
        return SourceEventEmitted(
            source_name=source.source_id,
            payload=output.to_dict(),
            output_dict=output.to_dict(),
            context=TaskContext(
                session_id=None,
                turn_id=None,
                task_id=None,
                user_id=owner_user_id,
            ),
            source_id=source.source_id,
            metadata_dict=self._metadata_dict(metadata),
            policy_dict=source.memory_policy.to_dict(),
            projection_dict=projection.to_dict(),
            occurred_at=output.occurred_at,
            owner_user_id=owner_user_id,
            relation_candidates=self._relation_candidates(metadata),
            allowed_edge_whitelist=tuple(allowed_edge_whitelist or ()),
            source_fingerprint=source.source_item_version_fingerprint(output.to_dict()),
            idempotency_key=source.idempotency_key(output),
            memory_event_type=str(getattr(source, "memory_event_type", "SOURCE_EVENT")),
            l2_batch_policy_dict=self._l2_batch_policy_dict(source, output),
        )

    @staticmethod
    def _metadata_dict(
        metadata: SourceOutputMetadata | None,
    ) -> dict[str, list[Any]] | None:
        if metadata is None:
            return None
        return {
            "entities": list(metadata.entities or []),
            "tags": list(metadata.tags or []),
            "relation_candidates": list(metadata.relation_candidates or []),
            "fact_hints": list(metadata.fact_hints or []),
        }

    @staticmethod
    def _relation_candidates(metadata: SourceOutputMetadata | None) -> tuple[Any, ...]:
        if metadata is not None and metadata.relation_candidates:
            return tuple(metadata.relation_candidates)
        return ()

    @staticmethod
    def _l2_batch_policy_dict(
        source: Source,
        output: SourceOutput,
    ) -> dict[str, Any] | None:
        policy = source.l2_batch_policy(output)
        if policy is None:
            return None
        return {
            "owner": policy.owner,
            "catch_up_owner": policy.catch_up_owner,
            "max_events": policy.max_events,
            "min_ready_events": policy.min_ready_events,
            "max_estimated_tokens": policy.max_estimated_tokens,
            "max_wait_seconds": policy.max_wait_seconds,
        }

    async def _publish_source_event(
        self,
        *,
        event: Event,
        source_id: str,
    ) -> bool:
        try:
            published = await self._event_bus.publish(event)
        except Exception:
            logger.exception("publish SourceEventEmitted failed (source=%s)", source_id)
            return False
        if not published:
            logger.warning(
                "SourceEventEmitted downstream projection publish was rejected",
                source_id=source_id,
                event_id=event.event_id,
            )
            return False
        return True

    @staticmethod
    def _resolve_memory_owner_user_id(output: SourceOutput) -> str:
        """Phase H+2 identity layer ingress #5 (source side).

        Source outputs may stash a user_id in provenance / domain_payload
        — historically a system-level source (screenshot_timeline,
        photo_library, browser_history) leaves it empty and falls
        through to DEFAULT_USER_ID. A future per-user source might
        populate it with a channel-specific identifier; in that case
        the value MUST get canonicalized before reaching memory L1,
        same contract as the four other ingress sites.

        Returns a canonical user_id string in all cases; ``raw_value``
        flows through ``canonicalize_user_id`` so any ``channel_*``
        prefix collapses to the canonical local user.
        """
        for container in (output.provenance, output.domain_payload):
            if not isinstance(container, dict):
                continue
            for key in ("memory_owner_user_id", "owner_user_id", "user_id"):
                raw_value = str(container.get(key) or "").strip()
                if raw_value:
                    return str(_canonicalize_user_id(raw_value))
        return str(_canonicalize_user_id(DEFAULT_USER_ID))
