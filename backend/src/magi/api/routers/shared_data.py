"""Owner-facing source data browsing over retained, governed source revisions."""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, JsonValue

from ...core.container import get_container
from ...core.device_models import collection_capability
from ...plugins.operation_execution import plugin_runtime_operation

shared_data_router = APIRouter()
Selector = Annotated[str | None, Query(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SharedDataSource(DataModel):
    connection_id: str
    source_id: str
    source_type: str
    plugin_id: str
    display_name: str
    connection_epoch: str


class SharedDataSources(DataModel):
    items: list[SharedDataSource]


class SharedDataRecord(DataModel):
    id: int
    object_id: str
    version: str
    payload: dict[str, JsonValue]


class SharedDataPage(DataModel):
    items: list[SharedDataRecord]
    next_before: int | None


class SourceDeliveryRecord(DataModel):
    id: int
    status: Literal["pending", "claimed", "completed", "failed"]
    received_at_ms: int
    processed_at_ms: int | None


class SourceDeliveryPage(DataModel):
    items: list[SourceDeliveryRecord]
    next_before: int | None
    completed_retention_limit: int


class SharedDataRetryRequest(DataModel):
    connection_epoch: str


class SharedDataRetryResponse(DataModel):
    success: bool


async def _sources() -> list[SharedDataSource]:
    container = get_container()
    store = container.source_scheduler_contrib().source_store
    manager = container.plugin_manager()
    result: dict[tuple[str, str], SharedDataSource] = {}
    for row in await store.shared_sources():
        try:
            connection = manager.connection_store.get(row["connection_id"])
        except KeyError:
            continue
        result[(row["connection_id"], row["source_id"])] = SharedDataSource(
            **row, display_name=connection.display_name,
            connection_epoch=manager.connection_store.ingress_epoch(row["connection_id"]),
        )
    registry = container.source_registry()
    for item in registry.list_contributions():
        if collection_capability(item.metadata) is None:
            continue
        connection_id = item.metadata["connection_id"]
        source_type = item.metadata["source_type"]
        resolved = registry.resolve_source(source_type, connection_id=connection_id)
        if resolved is None:
            continue
        plugin_id, _, source, _ = resolved
        connection = manager.connection_store.get(connection_id)
        result[(connection_id, source.source_id)] = SharedDataSource(
            connection_id=connection_id, source_id=source.source_id, source_type=source_type,
            plugin_id=plugin_id, display_name=connection.display_name,
            connection_epoch=manager.connection_store.ingress_epoch(connection_id),
        )
    return sorted(result.values(), key=lambda item: (item.source_type, item.connection_id, item.source_id))


async def _source(connection_id: str, source_id: str) -> SharedDataSource:
    for item in await _sources():
        if (item.connection_id, item.source_id) == (connection_id, source_id):
            return item
    raise HTTPException(404, "Shared data source not found")


@shared_data_router.get("/shared", response_model=SharedDataSources)
async def list_shared_sources() -> SharedDataSources:
    async with plugin_runtime_operation():
        return SharedDataSources(items=await _sources())


@shared_data_router.get("/shared/{connection_id}/{source_id}/records", response_model=SharedDataPage)
async def list_shared_records(
    connection_id: str, source_id: str,
    before: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    field: Selector = None, value: Annotated[str | None, Query(max_length=256)] = None,
    date_field: Selector = None,
    since: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    until: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
) -> SharedDataPage:
    if (field is None) != (value is None) or ((since is not None or until is not None) and date_field is None):
        raise HTTPException(422, "Incomplete data filter")
    if since is not None and until is not None and since >= until:
        raise HTTPException(422, "Invalid date range")
    async with plugin_runtime_operation():
        await _source(connection_id, source_id)
        container = get_container()
        store = container.source_scheduler_contrib().source_store
        memory = container.unified_memory()
        # A bounded scan permits privacy filtering without exposing hidden totals.
        items: list[SharedDataRecord] = []
        cursor = before
        for _ in range(10):
            rows = await store.shared_records(connection_id=connection_id, source_id=source_id,
                before=cursor, limit=limit, field=field, value=value,
                date_field=date_field, since=since, until=until)
            if not rows:
                return SharedDataPage(items=items, next_before=None)
            for row in rows:
                cursor = row["id"]
                if await memory.l1.get_user_visible_event(row["memory_event_id"]) is not None:
                    items.append(SharedDataRecord(**{key: row[key] for key in ("id", "object_id", "version", "payload")}))
                if len(items) == limit:
                    return SharedDataPage(items=items, next_before=cursor)
            if len(rows) < limit:
                return SharedDataPage(items=items, next_before=None)
        return SharedDataPage(items=items, next_before=cursor)


@shared_data_router.get("/shared/{connection_id}/{source_id}/history", response_model=SourceDeliveryPage)
async def list_source_deliveries(
    connection_id: str, source_id: str,
    before: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SourceDeliveryPage:
    async with plugin_runtime_operation():
        source = await _source(connection_id, source_id)
        rows = await get_container().runtime_trace_store().source_delivery_history(
            connection_id=connection_id, source_type=source.source_type, before=before, limit=limit + 1,
        )
        return SourceDeliveryPage(items=[SourceDeliveryRecord(**row) for row in rows[:limit]],
            next_before=rows[limit - 1]["id"] if len(rows) > limit else None, completed_retention_limit=1000)


@shared_data_router.post("/shared/{connection_id}/{source_id}/history/{delivery_id}/retry", response_model=SharedDataRetryResponse)
async def retry_source_delivery(connection_id: str, source_id: str, delivery_id: int,
                                request: SharedDataRetryRequest) -> SharedDataRetryResponse:
    async with plugin_runtime_operation():
        source = await _source(connection_id, source_id)
        if request.connection_epoch != source.connection_epoch:
            raise HTTPException(409, "Source connection changed")
        await get_container().runtime_trace_store().retry_source_delivery(
            connection_id=connection_id, source_type=source.source_type, delivery_id=delivery_id,
        )
        return SharedDataRetryResponse(success=True)
