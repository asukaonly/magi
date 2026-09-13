"""Bounded, authenticated background fact admission (epoch enforced by gateway)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ...core.container import get_container
from ...notifications.store import get_notification_store
from ...runtime_trace.contracts import PluginIngressEventRecord

Key = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PluginEvent(StrictModel):
    kind: Literal["plugin_event"]
    plugin_target: Key
    event_type: Key
    data: dict[str, JsonValue]


class NotificationRead(StrictModel):
    kind: Literal["notification_read"]
    notification_id: Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]


class BackgroundEvent(StrictModel):
    event_id: UUID
    stream: Key
    sequence: Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
    occurred_at_ms: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    payload: Annotated[PluginEvent | NotificationRead, Field(discriminator="kind")]

    @model_validator(mode="after")
    def bounded_payload(self) -> BackgroundEvent:
        if len(self.payload.model_dump_json().encode()) > 65536:
            raise ValueError("Background event exceeds size limit")
        return self


class DeliveryBatch(StrictModel):
    server_id: UUID
    data_epoch: UUID
    producer_id: UUID
    events: Annotated[list[BackgroundEvent], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_events(self) -> DeliveryBatch:
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("Duplicate event identity in batch")
        if len({e.stream for e in self.events}) != len(self.events):
            raise ValueError("Only one event per stream may be in flight")
        return self


class EventReceipt(StrictModel):
    event_id: UUID
    status: Literal["accepted", "retry", "rejected"]
    code: str


class DeliveryReceipt(StrictModel):
    server_id: UUID
    data_epoch: UUID
    receipts: list[EventReceipt]


delivery_router = APIRouter()


@delivery_router.post("/events", response_model=DeliveryReceipt)
async def deliver(batch: DeliveryBatch) -> DeliveryReceipt:
    """ACK each fact only after its durable admission or idempotent materialization."""
    container = get_container()
    store = container.runtime_trace_store()
    registry = container.plugin_ingress_registry()
    receipts = []
    for event in batch.events:
        code = "accepted"
        status = "accepted"
        try:
            payload = event.payload
            if isinstance(payload, NotificationRead):
                # Exact-ID, monotonic transition: replay cannot mark newer notifications read.
                await asyncio.to_thread(
                    get_notification_store().mark_read, [payload.notification_id]
                )
            elif not registry.ready:
                code, status = "processor_unavailable", "retry"
            else:
                code = await store.accept_background_event(
                    allow_new=registry.accepts_delivery(payload.plugin_target, payload.event_type),
                    producer_id=str(batch.producer_id),
                    data_epoch=str(batch.data_epoch),
                    event_id=str(event.event_id),
                    stream=event.stream,
                    sequence=event.sequence,
                    record=PluginIngressEventRecord(
                        event_id=0,
                        source_kind="background_delivery",
                        producer=str(batch.producer_id),
                        plugin_target=payload.plugin_target,
                        event_type=payload.event_type,
                        occurred_at_ms=event.occurred_at_ms,
                        payload_json=json.dumps(payload.data, ensure_ascii=False),
                    ),
                )
                status = (
                    "accepted"
                    if code == "accepted"
                    else "retry"
                    if code == "inbox_full"
                    else "rejected"
                )
        except sqlite3.Error:
            code, status = "storage_unavailable", "retry"
        receipts.append(EventReceipt(event_id=event.event_id, status=status, code=code))
    return DeliveryReceipt(
        server_id=batch.server_id, data_epoch=batch.data_epoch, receipts=receipts
    )


@delivery_router.get("/status")
async def delivery_status() -> dict[str, int]:
    return await get_container().runtime_trace_store().background_delivery_status()


@delivery_router.post("/retry")
async def retry_delivery() -> dict[str, bool]:
    await get_container().runtime_trace_store().retry_failed_background_deliveries()
    return {"ok": True}
