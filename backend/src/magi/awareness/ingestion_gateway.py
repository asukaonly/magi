"""Sensor ingestion publisher.

Builds a SensorEventEmitted payload from sensor + output + metadata and publishes
to the event bus. Side-effects (memory / timeline / KG / sensor_state) are handled
by independent subscribers (see magi.awareness.subscribers).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from ulid import ULID

from ..core.logger import get_logger
from ..events.events import Event, EventTypes
from ..events.domain_payloads import SensorEventEmitted, TaskContext
from ..identity import canonicalize_user_id as _canonicalize_user_id
from ..runtime_defaults import DEFAULT_USER_ID
from .sensor_base import SensorBase
from .sensor_output import SensorOutput, SensorOutputMetadata
from .sensor_projection import build_sensor_projection

logger = get_logger(__name__)


@dataclass(slots=True)
class SensorIngestionResult:
    """Outcome of a sensor ingestion publish."""

    event_id: str
    ingested: bool = True
    stats: dict[str, Any] = field(default_factory=dict)


class SensorIngestionGateway:
    """Publishes SensorEventEmitted; lets subscribers handle side effects."""

    def __init__(self, *, event_bus) -> None:
        self._event_bus = event_bus

    async def ingest(
        self,
        sensor: SensorBase,
        output: SensorOutput,
        metadata: SensorOutputMetadata | None = None,
        *,
        allowed_edge_whitelist: list[str] | None = None,
    ) -> SensorIngestionResult:
        event_id = str(ULID())
        owner_user_id = self._resolve_memory_owner_user_id(output)
        projection = build_sensor_projection(sensor, output, metadata)

        # Compute sensor-attached values now; subscribers can't reach sensor.
        idempotency_key = sensor.idempotency_key(output)
        memory_event_type = str(getattr(sensor, "memory_event_type", "SENSOR_EVENT"))
        fingerprint = sensor.source_item_version_fingerprint(output.to_dict())
        l2_batch_policy = sensor.l2_batch_policy(output)
        l2_batch_dict: dict[str, Any] | None = None
        if l2_batch_policy is not None:
            l2_batch_dict = {
                "owner": l2_batch_policy.owner,
                "catch_up_owner": l2_batch_policy.catch_up_owner,
                "max_events": l2_batch_policy.max_events,
                "min_ready_events": l2_batch_policy.min_ready_events,
                "max_estimated_tokens": l2_batch_policy.max_estimated_tokens,
                "max_wait_seconds": l2_batch_policy.max_wait_seconds,
            }

        relation_candidates: tuple = ()
        if metadata is not None and metadata.relation_candidates:
            relation_candidates = tuple(metadata.relation_candidates)

        metadata_dict = None
        if metadata is not None:
            metadata_dict = {
                "entities": list(metadata.entities or []),
                "tags": list(metadata.tags or []),
                "relation_candidates": list(metadata.relation_candidates or []),
                "fact_hints": list(metadata.fact_hints or []),
            }

        payload = SensorEventEmitted(
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
            metadata_dict=metadata_dict,
            policy_dict=sensor.memory_policy.to_dict(),
            projection_dict=projection.to_dict(),
            occurred_at=output.occurred_at,
            owner_user_id=owner_user_id,
            relation_candidates=relation_candidates,
            allowed_edge_whitelist=tuple(allowed_edge_whitelist or ()),
            sensor_fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            memory_event_type=memory_event_type,
            l2_batch_policy_dict=l2_batch_dict,
        )

        try:
            await self._event_bus.publish(
                Event(
                    type=EventTypes.SENSOR_EVENT_EMITTED,
                    data=payload,
                    event_id=event_id,
                    source="sensor_ingestion_gateway",
                )
            )
        except Exception:
            logger.exception(
                "publish SensorEventEmitted failed (sensor=%s)", sensor.sensor_id
            )

        return SensorIngestionResult(event_id=event_id, ingested=True, stats={})

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
