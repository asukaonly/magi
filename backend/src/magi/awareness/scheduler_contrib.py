"""Source layer's integration with the unified scheduler."""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from ..core.container import get_container
from ..i18n import get_preferred_language
from ..core.logger import get_logger
from ..plugins.i18n import get_current_language as get_plugin_current_language
from ..plugins.i18n import set_current_language as set_plugin_current_language
from ..plugins.sources import SourceRegistry
from ..scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
    build_source_schedule_id,
    build_source_target_key,
)
from ..scheduler.service import SchedulerService
from ..utils.runtime import RuntimePaths
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch
from ..plugins.operation_execution import plugin_runtime_operation
from .source_sync import SourceSyncContext, ScopedSourceRuntimePaths
from .source_store import SourceCheckpointConflict, SourceStore, source_change_digest
from .source_ingestion import SourceBatchIngestor

if TYPE_CHECKING:
    from .ingestion_gateway import SourceIngestionGateway

logger = get_logger(__name__)


@dataclass(slots=True)
class _ResolvedSourceSyncTarget:
    plugin_id: str
    source: Any
    spec: Any


@dataclass(slots=True)
class _SourceSyncSettings:
    package_settings: dict[str, Any]
    allowed_edge_whitelist: list[str]
    limit: int


def request_source_schedule_refresh() -> None:
    """Schedule a best-effort refresh of source-owned schedules."""
    try:
        contrib = _get_source_scheduler_contrib()
    except RuntimeError:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("Skipping source schedule refresh because no event loop is running")
        return

    task = loop.create_task(contrib.sync_schedules())
    task.add_done_callback(_log_refresh_failure)


def _get_source_scheduler_contrib():
    provider = get_container().source_scheduler_contrib
    instance = provider()
    if instance is None:
        raise RuntimeError("source_scheduler_contrib binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError("source_scheduler_contrib binding is not initialized")
    return instance


def _log_refresh_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception as exc:  # pragma: no cover
        logger.warning("Source schedule refresh failed", error=str(exc))


class SourceSchedulerContrib:
    """Source layer's scheduler contributor."""

    def __init__(
        self,
        *,
        scheduler_service: SchedulerService,
        source_registry: SourceRegistry,
        plugin_manager: Any,
        runtime_paths: RuntimePaths,
        get_config: Callable[[], Any],
        ingestion_gateway: SourceIngestionGateway,
        source_store: SourceStore | None = None,
    ) -> None:
        self._scheduler_service = scheduler_service
        self._source_registry = source_registry
        self._plugin_manager = plugin_manager
        self._runtime_paths = runtime_paths
        self._get_config = get_config
        self._ingestion_gateway = ingestion_gateway
        self.source_store = source_store or SourceStore(runtime_paths.runtime_dir / "plugin_sources.db")
        self._source_ingestor = SourceBatchIngestor(store=self.source_store, gateway=ingestion_gateway)
        self._source_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._registered_schedule_ids: set[str] = set()

    async def register_schedules(self, scheduler: SchedulerService) -> None:
        scheduler.register_handler(
            ScheduledTargetType.SOURCE_SYNC,
            self._handle_source_sync,
        )
        await self.sync_schedules()

    async def unregister_schedules(self, scheduler: SchedulerService) -> None:
        for schedule_id in list(self._registered_schedule_ids):
            try:
                await scheduler.unschedule(
                    schedule_id,
                    target_type=ScheduledTargetType.SOURCE_SYNC,
                    target_key="",
                )
            except Exception:
                pass
        self._registered_schedule_ids.clear()

    async def sync_schedules(self) -> None:
        desired_schedule_ids: set[str] = set()
        for contribution in self._source_registry.list_contributions():
            source_type = str(
                contribution.metadata.get("source_type")
                or contribution.contribution_id.split(".")[-1]
            )
            connection_id = str(contribution.metadata.get("connection_id") or "")
            if not connection_id:
                raise RuntimeError("Source contribution is missing its connection identity")
            resolved = self._source_registry.resolve_source(source_type, connection_id=connection_id)
            if resolved is None:
                continue
            plugin_id, _, source, spec = resolved
            schedule_id = build_source_schedule_id(connection_id, source_type)
            current_settings = source.connection.settings
            default_settings = dict(spec.metadata.get("default_settings", {}))
            source_settings = dict(current_settings.get("sources", {}).get(source_type, {}))
            enabled = source.connection.enabled and bool(source_settings.get("enabled", default_settings.get("enabled", True)))
            sync_mode = str(
                source_settings.get("sync_mode", default_settings.get("sync_mode", spec.sync_mode))
            )
            interval_minutes = float(
                source_settings.get(
                    "sync_interval_minutes", default_settings.get("sync_interval_minutes", 1)
                )
            )
            supports_pull_sync = bool(getattr(source, "supports_pull_sync", False))
            if (not enabled) or (not supports_pull_sync) or sync_mode == "manual":
                await self._scheduler_service.unschedule(
                    schedule_id,
                    target_type=ScheduledTargetType.SOURCE_SYNC,
                    target_key=build_source_target_key(connection_id, source_type),
                )
                self._registered_schedule_ids.discard(schedule_id)
                continue
            if sync_mode == "watch" and not bool(getattr(source, "supports_watch_mode", False)):
                interval_minutes = max(1.0, interval_minutes)
            await self._scheduler_service.schedule_interval(
                schedule_id=schedule_id,
                target_type=ScheduledTargetType.SOURCE_SYNC,
                target_key=build_source_target_key(connection_id, source_type),
                seconds=max(1.0, interval_minutes * 60.0),
                target_payload={
                    "plugin_id": plugin_id,
                    "connection_id": connection_id,
                    "source_type": source_type,
                    "manual": False,
                },
                metadata={"source_type": source_type, "plugin_id": plugin_id, "connection_id": connection_id},
            )
            self._registered_schedule_ids.add(schedule_id)
            desired_schedule_ids.add(schedule_id)
        for removed_id in self._registered_schedule_ids - desired_schedule_ids:
            await self._scheduler_service.unschedule(removed_id, target_type=ScheduledTargetType.SOURCE_SYNC, target_key="")
        self._registered_schedule_ids.intersection_update(desired_schedule_ids)

    async def queue_manual_sync(
        self,
        source_type: str,
        *,
        connection_id: str,
        first_context: bool = False,
        sync_mode: str = "latest",
        backfill_scope: str | None = None,
        backfill_days: int | None = None,
        backfill_start_date: str | None = None,
        backfill_end_date: str | None = None,
    ) -> ScheduleDefinition:
        resolved = self._source_registry.resolve_source(source_type, connection_id=connection_id)
        if resolved is None:
            raise KeyError(source_type)
        plugin_id, _, source, _ = resolved
        if not bool(getattr(source, "supports_pull_sync", False)):
            raise ValueError(f"Source does not support pull sync: {source_type}")
        normalized_mode = "backfill" if sync_mode == "backfill" else "latest"
        normalized_scope = str(backfill_scope or "last_30_days").strip() or "last_30_days"
        normalized_start_date = _normalize_optional_date(backfill_start_date)
        normalized_end_date = _normalize_optional_date(backfill_end_date)
        if normalized_mode == "backfill":
            schedule_suffix = normalized_scope
            if normalized_scope == "custom" and normalized_start_date and normalized_end_date:
                schedule_suffix = f"custom:{normalized_start_date}:{normalized_end_date}"
            schedule_id = f"source-sync-backfill:{connection_id}:{source_type}:{schedule_suffix}"
        else:
            schedule_id = f"source-sync-manual:{connection_id}:{source_type}:{uuid.uuid4().hex}"
        target_payload = {
            "plugin_id": plugin_id,
            "connection_id": connection_id,
            "source_type": source_type,
            "manual": True,
        }
        metadata = {"manual": True, "source_type": source_type, "plugin_id": plugin_id, "connection_id": connection_id}
        if first_context:
            target_payload["first_context"] = True
            metadata["first_context"] = True
        if normalized_mode == "backfill":
            sync_request: dict[str, Any] = {
                "mode": "backfill",
                "backfill_scope": normalized_scope,
            }
            if backfill_days is not None:
                sync_request["backfill_days"] = int(backfill_days)
            if normalized_start_date is not None:
                sync_request["backfill_start_date"] = normalized_start_date
            if normalized_end_date is not None:
                sync_request["backfill_end_date"] = normalized_end_date
            target_payload["sync_request"] = dict(sync_request)
            metadata["sync_request"] = dict(sync_request)
        return await self._scheduler_service.schedule_once(
            schedule_id=schedule_id,
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(connection_id, source_type),
            run_at=time.time(),
            target_payload=target_payload,
            metadata=metadata,
        )

    async def _handle_source_sync(
        self,
        context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        source_type = str(context.schedule.target_payload.get("source_type") or "")
        return await self._run_source_sync(
            schedule_id=context.schedule.schedule_id,
            target_key=context.schedule.target_key,
            source_type=source_type,
            manual=context.manual,
            target_state=context.target_state,
            sync_payload=context.schedule.target_payload,
            admitted_at=context.triggered_at,
        )

    async def queue_source_change(self, payload: dict[str, Any]) -> ScheduleDefinition:
        """Durably queue broker-bound source ingress without reentering its worker."""
        connection_id = str(payload.get("connection_id") or "")
        source_type = str(payload.get("source_type") or "")
        if not connection_id or not source_type:
            raise ValueError("Source ingress requires connection and source identities")
        change = SourceChange.model_validate(payload.get("source_change"))
        target = self._resolve_source_sync_target(source_type, connection_id=connection_id, require_pull=False)
        self._source_sync_settings(connection=target.source.connection, source_type=source_type, spec=target.spec)
        return await self._scheduler_service.schedule_once(
            schedule_id=f"source-ingress:{connection_id}:{uuid.uuid4().hex}",
            target_type=ScheduledTargetType.SOURCE_SYNC,
            target_key=build_source_target_key(connection_id, source_type),
            run_at=time.time(),
            target_payload={
                "plugin_id": target.plugin_id, "connection_id": connection_id,
                "source_type": source_type, "manual": False,
                "source_change": change.model_dump(mode="json"),
            },
            metadata={"connection_id": connection_id, "source_type": source_type, "trigger": "ingress"},
        )

    async def execute_source_sync_job(self, job: dict[str, object]) -> ScheduledExecutionResult:
        target_state = await self._scheduler_service.get_target_state(
            ScheduledTargetType(str(job["target_type"])),
            str(job["target_key"]),
        )
        return await self._run_source_sync(
            schedule_id=str(job["schedule_id"]),
            target_key=str(job["target_key"]),
            source_type=str(job["source_type"]),
            manual=bool(job["manual"]),
            target_state=target_state,
            sync_payload=job.get("payload") if isinstance(job.get("payload"), dict) else {},
            admitted_at=float(job.get("created_at") or 0.0),
        )

    async def flush_source_state(self, source_type: str, *, connection_id: str) -> dict[str, Any]:
        async with plugin_runtime_operation():
            return await self._flush_admitted_source_state(source_type, connection_id=connection_id)

    async def _flush_admitted_source_state(self, source_type: str, *, connection_id: str) -> dict[str, Any]:
        resolved = self._source_registry.resolve_source(source_type, connection_id=connection_id)
        if resolved is None:
            raise RuntimeError(f"Source not found: {source_type}")
        plugin_id, _, source, spec = resolved
        self._source_sync_settings(connection=source.connection, source_type=source_type, spec=spec)
        flush_state = getattr(source, "flush_runtime_state", None)
        if not callable(flush_state):
            raise RuntimeError(f"Source does not support state flush: {source_type}")
        return await flush_state(
            runtime_paths=ScopedSourceRuntimePaths(connection_id, plugin_id, source.context.state_dir),
            plugin_settings=copy.deepcopy(source.connection.settings),
        )

    async def _run_source_sync(
        self,
        *,
        schedule_id: str,
        target_key: str,
        source_type: str,
        manual: bool,
        target_state: Any,
        sync_payload: dict[str, Any] | None = None,
        admitted_at: float = 0.0,
    ) -> ScheduledExecutionResult:
        connection_id = str((sync_payload or {}).get("connection_id") or "")
        if not connection_id:
            raise ValueError("Source sync requires an explicit connection identity")
        lock = self._source_locks.setdefault((connection_id, source_type), asyncio.Lock())
        async with plugin_runtime_operation(), lock:
            return await self._run_admitted_source_sync(
                schedule_id=schedule_id, target_key=target_key, source_type=source_type,
                connection_id=connection_id, manual=manual, target_state=target_state,
                sync_payload=sync_payload, admitted_at=admitted_at,
            )

    async def _run_admitted_source_sync(
        self, *, schedule_id: str, target_key: str, source_type: str,
        connection_id: str, manual: bool, target_state: Any,
        sync_payload: dict[str, Any] | None, admitted_at: float,
    ) -> ScheduledExecutionResult:
        pushed_change = (
            SourceChange.model_validate(sync_payload["source_change"])
            if sync_payload and "source_change" in sync_payload else None
        )
        target = self._resolve_source_sync_target(source_type, connection_id=connection_id, require_pull=pushed_change is None)
        connection = target.source.connection
        settings = self._source_sync_settings(
            connection=connection, source_type=source_type, spec=target.spec,
        )
        sync_request = _extract_backfill_sync_request(sync_payload)
        checkpoint = await self.source_store.checkpoint(connection, target.source.source_id, source_type)
        pending = await self.source_store.pending(checkpoint)
        if pushed_change is not None and pending is not None:
            if len(pending.batch.changes) != 1 or (
                pending.batch.changes[0].object_id, pending.batch.changes[0].version
            ) != (pushed_change.object_id, pushed_change.version):
                raise SourceCheckpointConflict("A preceding source batch must finish before ingress can proceed")
            version = await self.source_store.version(checkpoint, pushed_change)
            if version["digest"] != source_change_digest(pushed_change):
                raise ValueError("A source object revision cannot be reused for different content")
        last_cursor = checkpoint.cursor
        if sync_request is not None:
            settings = _apply_backfill_sync_request(settings=settings, source_type=source_type, sync_request=sync_request)
            if pending is None and not schedule_id.startswith("source-sync-continuation:"):
                last_cursor = None
        preferred_language = get_preferred_language()
        if preferred_language:
            settings.package_settings.setdefault("locale", preferred_language)
        previous_language = get_plugin_current_language()
        set_plugin_current_language(preferred_language or None)
        try:
            ingestion_boundary = await self._ingestion_gateway.capture_ingestion_boundary()
            allow_pre_clear_events = bool(manual and (
                ingestion_boundary.clear_generation == 0 or admitted_at > ingestion_boundary.clear_cutoff_at
            ))
            if pending is None:
                if pushed_change is not None:
                    result = SourceChangeBatch(changes=[pushed_change], next_cursor=checkpoint.cursor)
                else:
                    result = await target.source.collect_items(SourceSyncContext(
                        connection_id=connection.connection_id,
                        source_type=source_type, manual=manual, last_cursor=last_cursor,
                        last_success_at=target_state.last_success_at, limit=settings.limit,
                        runtime_paths=ScopedSourceRuntimePaths(connection.connection_id, connection.plugin_id, target.source.context.state_dir),
                        plugin_settings=settings.package_settings,
                    ))
                if not isinstance(result, SourceChangeBatch):
                    raise TypeError("Sources must return SourceChangeBatch")
                if not result.complete and result.next_cursor == last_cursor:
                    raise ValueError("Incomplete source batch must advance its opaque cursor")
                pending = await self.source_store.stage_batch(connection, checkpoint, result)
            result = pending.batch
            package = self._plugin_manager.get_package(target.plugin_id)
            if package is None:
                raise RuntimeError("Source plugin package is no longer installed")
            accepted = await self._source_ingestor.ingest(
                connection=connection, source=target.source, pending=pending,
                boundary=ingestion_boundary, rule_revision=package.manifest.version,
                allowed_edge_whitelist=settings.allowed_edge_whitelist,
                allow_pre_clear_events=allow_pre_clear_events,
                provenance={"scheduler_schedule_id": schedule_id, "scheduler_target_key": target_key,
                            "source_sync_mode": "manual" if manual else "scheduled"},
            )
            stats = dict(_merge_sync_request_stats(result.stats, sync_request) or {})
            stats.update({"has_more": not result.complete, "continue_sync": not result.complete,
                          "backfill_has_more": not result.complete, "connection_id": connection.connection_id})
            return ScheduledExecutionResult(
                success=True, message="source_sync_completed", next_cursor=accepted.cursor,
                watermark_ts=result.watermark_ts, stats=stats,
            )
        finally:
            set_plugin_current_language(previous_language or None)

    def _resolve_source_sync_target(self, source_type: str, *, connection_id: str, require_pull: bool = True) -> _ResolvedSourceSyncTarget:
        resolved = self._source_registry.resolve_source(source_type, connection_id=connection_id)
        if resolved is None:
            raise RuntimeError(f"Source not found: {source_type}")
        plugin_id, _, source, spec = resolved
        if require_pull and not bool(getattr(source, "supports_pull_sync", False)):
            raise RuntimeError(f"Source does not support pull sync: {source_type}")
        return _ResolvedSourceSyncTarget(plugin_id=plugin_id, source=source, spec=spec)

    def _source_sync_settings(
        self,
        *,
        connection: Any,
        source_type: str,
        spec: Any,
    ) -> _SourceSyncSettings:
        if not connection.enabled:
            raise PermissionError("Source connection is disabled")
        package_settings = copy.deepcopy(connection.settings)
        source_settings = dict(package_settings.get("sources", {}).get(source_type, {}))
        default_settings = spec.metadata.get("default_settings", {})
        if not source_settings.get("enabled", default_settings.get("enabled", True)):
            raise PermissionError("Source is disabled")
        allowed_edge_whitelist = [
            str(edge_type)
            for edge_type in source_settings.get(
                "edge_whitelist",
                default_settings.get("edge_whitelist", []),
            )
        ]
        return _SourceSyncSettings(
            package_settings=package_settings,
            allowed_edge_whitelist=allowed_edge_whitelist,
            limit=int(source_settings.get("max_items_per_sync", 200)),
        )

def _extract_backfill_sync_request(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    request = payload.get("sync_request")
    if not isinstance(request, dict):
        return None
    if request.get("mode") != "backfill":
        return None
    scope = str(request.get("backfill_scope") or "last_30_days").strip() or "last_30_days"
    normalized: dict[str, Any] = {
        "mode": "backfill",
        "backfill_scope": scope,
    }
    days = request.get("backfill_days")
    if days is not None:
        try:
            normalized["backfill_days"] = int(days)
        except (TypeError, ValueError):
            pass
    start_date = _normalize_optional_date(request.get("backfill_start_date"))
    end_date = _normalize_optional_date(request.get("backfill_end_date"))
    if start_date is not None:
        normalized["backfill_start_date"] = start_date
    if end_date is not None:
        normalized["backfill_end_date"] = end_date
    return normalized


def _apply_backfill_sync_request(
    *,
    settings: _SourceSyncSettings,
    source_type: str,
    sync_request: dict[str, Any],
) -> _SourceSyncSettings:
    package_settings = copy.deepcopy(settings.package_settings)
    sources_settings = package_settings.get("sources")
    if not isinstance(sources_settings, dict):
        sources_settings = {}
        package_settings["sources"] = sources_settings
    source_settings = sources_settings.get(source_type)
    if not isinstance(source_settings, dict):
        source_settings = {}
    else:
        source_settings = dict(source_settings)
    sources_settings[source_type] = source_settings

    if sync_request.get("backfill_scope") == "custom":
        source_settings["initial_sync_policy"] = "custom_range"
        source_settings.pop("initial_sync_lookback_days", None)
        start_date = _normalize_optional_date(sync_request.get("backfill_start_date"))
        end_date = _normalize_optional_date(sync_request.get("backfill_end_date"))
        if start_date is not None:
            source_settings["initial_sync_start_date"] = start_date
        if end_date is not None:
            source_settings["initial_sync_end_date"] = end_date
    elif sync_request.get("backfill_scope") == "full":
        source_settings["initial_sync_policy"] = "full"
        source_settings.pop("initial_sync_lookback_days", None)
    else:
        source_settings["initial_sync_policy"] = "lookback_days"
        days = sync_request.get("backfill_days")
        if days is not None:
            source_settings["initial_sync_lookback_days"] = int(days)

    return _SourceSyncSettings(
        package_settings=package_settings,
        allowed_edge_whitelist=settings.allowed_edge_whitelist,
        limit=settings.limit,
    )


def _normalize_optional_date(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _merge_sync_request_stats(
    stats: dict[str, Any] | None,
    sync_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if sync_request is None:
        return stats
    merged = dict(stats or {})
    merged["sync_request"] = dict(sync_request)
    return merged
