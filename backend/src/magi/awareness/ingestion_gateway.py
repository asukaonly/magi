"""Sensor ingestion publisher.

Builds a SensorEventEmitted payload, commits it to L1 memory, then publishes the
committed event for downstream timeline, graph, and sensor-state projections.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol
from ulid import ULID

from ..core.logger import get_logger
from ..events.events import Event, EventTypes
from ..events.domain_payloads import SensorEventEmitted, TaskContext
from ..memory.sensor_ingestion import SensorCommitOutcome, SensorCommitReceipt
from ..identity import canonicalize_user_id as _canonicalize_user_id
from ..identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from .sensor_base import SensorBase
from .sensor_output import SensorOutput, SensorOutputMetadata
from .sensor_projection import build_sensor_projection

logger = get_logger(__name__)


class SensorMemoryCommitter(Protocol):
    """Memory-owned port that proves the terminal L1 outcome of a sensor event."""

    async def commit(self, event: Event) -> SensorCommitReceipt: ...


@dataclass(slots=True)
class SensorIngestionResult:
    """Outcome of an authoritative sensor-memory commit."""

    event_id: str
    ingested: bool = True
    stats: dict[str, Any] = field(default_factory=dict)


class SensorIngestionGateway:
    """Commit sensor events to memory before publishing derived projections."""

    def __init__(self, *, event_bus, memory_committer: SensorMemoryCommitter) -> None:
        self._event_bus = event_bus
        self._memory_committer = memory_committer

    async def ingest(
        self,
        sensor: SensorBase,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None = None,
        *,
        allowed_edge_whitelist: list[str] | None = None,
    ) -> SensorIngestionResult:
        event_id = str(ULID())
        payload = self._build_sensor_event_payload(
            sensor=sensor,
            output=output,
            metadata=metadata,
            allowed_edge_whitelist=allowed_edge_whitelist,
        )
        event = Event(
            type=EventTypes.SENSOR_EVENT_EMITTED,
            data=payload,
            event_id=event_id,
            source="sensor_ingestion_gateway",
        )
        receipt = await self._memory_committer.commit(event)
        committed_event = replace(event, event_id=receipt.event_id)
        projection_skipped = receipt.outcome is SensorCommitOutcome.GOVERNED_SKIP
        projection_published = (
            False
            if projection_skipped
            else await self._publish_sensor_event(
                event=committed_event,
                sensor_id=sensor.sensor_id,
            )
        )
        return SensorIngestionResult(
            event_id=receipt.event_id,
            ingested=True,
            stats={
                "memory_outcome": receipt.outcome.value,
                "projection_published": projection_published,
                "projection_skipped": projection_skipped,
            },
        )

    def _build_sensor_event_payload(
        self,
        *,
        sensor: SensorBase,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None,
        allowed_edge_whitelist: list[str] | None,
    ) -> SensorEventEmitted:
        owner_user_id = self._resolve_memory_owner_user_id(output)
        projection = build_sensor_projection(sensor, output, metadata)
        return SensorEventEmitted(
            sensor_name=sensor.sensor_id,
            payload=output.to_dict(),
            output_dict=output.to_dict(),
            context=TaskContext(
                session_id=None,
                turn_id=None,
                task_id=None,
                user_id=owner_user_id,
            ),
            sensor_id=sensor.sensor_id,
            metadata_dict=self._metadata_dict(metadata),
            policy_dict=sensor.memory_policy.to_dict(),
            projection_dict=projection.to_dict(),
            occurred_at=output.occurred_at,
            owner_user_id=owner_user_id,
            relation_candidates=self._relation_candidates(metadata),
            allowed_edge_whitelist=tuple(allowed_edge_whitelist or ()),
            sensor_fingerprint=sensor.source_item_version_fingerprint(output.to_dict()),
            idempotency_key=sensor.idempotency_key(output),
            memory_event_type=str(getattr(sensor, "memory_event_type", "SENSOR_EVENT")),
            l2_batch_policy_dict=self._l2_batch_policy_dict(sensor, output),
        )

    @staticmethod
    def _metadata_dict(
        metadata: SensorOutputMetadata | None,
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
    def _relation_candidates(metadata: SensorOutputMetadata | None) -> tuple[Any, ...]:
        if metadata is not None and metadata.relation_candidates:
            return tuple(metadata.relation_candidates)
        return ()

    @staticmethod
    def _l2_batch_policy_dict(
        sensor: SensorBase,
        output: SensorOutput,
    ) -> dict[str, Any] | None:
        policy = sensor.l2_batch_policy(output)
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

    async def _publish_sensor_event(
        self,
        *,
        event: Event,
        sensor_id: str,
    ) -> bool:
        try:
            published = await self._event_bus.publish(event)
        except Exception:
            logger.exception("publish SensorEventEmitted failed (sensor=%s)", sensor_id)
            return False
        if not published:
            logger.warning(
                "SensorEventEmitted downstream projection publish was rejected",
                sensor_id=sensor_id,
                event_id=event.event_id,
            )
            return False
        return True

    @staticmethod
    def _resolve_memory_owner_user_id(output: SensorOutput) -> str:
        """Phase H+2 identity layer ingress #5 (sensor side).

        Sensor outputs may stash a user_id in provenance / domain_payload
        — historically a system-level sensor (screenshot_timeline,
        photo_library, browser_history) leaves it empty and falls
        through to DEFAULT_USER_ID. A future per-user sensor might
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
