"""Timeline API router."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...config import get_config
from ...plugins import get_plugin_manager, get_sensor_registry
from ...timeline.retention import RetentionService
from ...timeline.service import TimelineService
from ...utils.runtime import get_runtime_paths
from ..routers.memory import get_unified_memory

timeline_router = APIRouter()


class TimelineManualEntryRequest(BaseModel):
    title: str
    summary: str
    text: str
    image_refs: list[str] = Field(default_factory=list)


def get_timeline_service() -> TimelineService:
    unified_memory = get_unified_memory()
    if unified_memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Timeline service unavailable",
        )
    return TimelineService(unified_memory)


def get_retention_service() -> RetentionService:
    return RetentionService()


def _get_nested_value(payload: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    return current


def _field_default_map(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {str(field.get("key")): field.get("default") for field in fields}


@timeline_router.get("/events")
async def list_timeline_events(
    limit: int = Query(default=50, ge=1, le=200),
    source_type: Optional[str] = Query(default=None),
):
    service = get_timeline_service()
    retention = get_retention_service()
    events = await service.list_events(limit=limit, source_type=source_type)
    return {
        "events": [
            {
                **event,
                "retention": retention.describe_event(event),
            }
            for event in events
        ],
        "count": len(events),
    }


@timeline_router.get("/events/{event_id}")
async def get_timeline_event(event_id: str):
    service = get_timeline_service()
    retention = get_retention_service()
    detail_loader = getattr(service, "get_event_detail", None)
    event = await detail_loader(event_id) if callable(detail_loader) else await service.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline event not found")
    return {
        **event,
        "retention": retention.describe_event(event),
    }


@timeline_router.post("/manual", status_code=status.HTTP_201_CREATED)
async def create_manual_entry(request: TimelineManualEntryRequest):
    service = get_timeline_service()
    event = await service.create_manual_journal(
        title=request.title,
        summary=request.summary,
        text=request.text,
        image_refs=request.image_refs,
    )
    return event.to_dict()


@timeline_router.get("/sources/status")
async def get_timeline_source_status():
    get_config()
    runtime_paths = get_runtime_paths()
    manager = get_plugin_manager()
    sensor_registry = get_sensor_registry()
    packages = {state.manifest.plugin_id: state for state in manager.list_packages()}
    contributions = [
        contribution
        for contribution in sensor_registry.list_contributions()
        if contribution.metadata.get("domain") == "timeline"
    ]
    return {
        "sources": [
            {
                "source_name": str(item.metadata.get("source_type") or item.contribution_id.split(".")[-1]),
                "plugin_id": item.plugin_id,
                "contribution_id": item.contribution_id,
                "display_name": item.display_name,
                "description": item.description,
                "fields": [field.model_dump() for field in item.fields],
                "current_settings": {
                    field.key: _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        field.key,
                        field.default,
                    )
                    for field in item.fields
                },
                "enabled": bool(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.enabled",
                        True,
                    )
                ),
                "sync_mode": str(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.sync_mode",
                        item.metadata.get("default_settings", {}).get("sync_mode", item.metadata.get("sync_mode", "manual")),
                    )
                ),
                "sync_interval_minutes": int(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.sync_interval_minutes",
                        item.metadata.get("default_settings", {}).get("sync_interval_minutes", 1),
                    )
                ),
                "default_retention_mode": str(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.default_retention_mode",
                        item.metadata.get("default_settings", {}).get("default_retention_mode", "analyze_only"),
                    )
                ),
                "storage_mode": str(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.storage_mode",
                        item.metadata.get("default_settings", {}).get("storage_mode", "managed"),
                    )
                ),
                "source_path": _get_nested_value(
                    packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                    f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.source_path",
                    item.metadata.get("default_settings", {}).get("source_path"),
                ),
                "fetch_page_content": bool(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.fetch_page_content",
                        item.metadata.get("default_settings", {}).get("fetch_page_content", False),
                    )
                ),
                "edge_whitelist": list(
                    _get_nested_value(
                        packages.get(item.plugin_id).current_settings if packages.get(item.plugin_id) is not None else {},
                        f"sensors.{str(item.metadata.get('source_type') or item.contribution_id.split('.')[-1])}.edge_whitelist",
                        item.metadata.get("default_settings", {}).get("edge_whitelist", []),
                    )
                ),
                "last_error": None,
                "last_success": None,
                "runtime_base_dir": str(runtime_paths.base_dir),
            }
            for item in contributions
        ]
    }


@timeline_router.post("/sources/{source_name}/sync")
async def trigger_timeline_source_sync(source_name: str):
    _ = get_config()
    sensor_registry = get_sensor_registry()
    resolved = sensor_registry.resolve_domain_sensor("timeline", source_name)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline source not found")
    return {"queued": True, "source_name": source_name}


@timeline_router.post("/events/{event_id}/reanalyze")
async def reanalyze_timeline_event(event_id: str):
    service = get_timeline_service()
    event = await service.reanalyze_event(event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timeline event not found")
    return {"queued": True, "event_id": event_id, "event": event}
