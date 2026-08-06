from __future__ import annotations

import asyncio
import copy
import io
import json
import sqlite3
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from _shared.memory_schema import apply_memory_shared_schema
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import manual_entries_routes as routes
from magi.api.routers.memory.router import memory_router
from magi.memory.l3.models import L3Candidate
from magi.memory.operation_barrier import AsyncOperationBarrier
from magi.memory.manual_entries import (
    ManualEntry,
    ManualEntryL1Projector,
    ManualEntryRecoveryService,
    ManualEntryStore,
)
from magi.memory.manual_entries.asset_store import ManualEntryAssetStore
from magi.memory.manual_entries.source_forgetting import (
    ManualEntrySourceForgetOwner,
)
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


def _entry(**overrides) -> ManualEntry:
    values = {
        "entry_id": "manual-1",
        "created_at": 100.0,
        "event_at": 100.0,
        "kind": "quick",
        "body": "before",
        "mood": None,
        "attachments": [],
        "l1_event_id": "event-old",
        "weather": {"code": 1, "temp_c": 20.0},
    }
    values.update(overrides)
    return ManualEntry(**values)


def test_manual_entry_routes_are_publicly_reachable() -> None:
    public = _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"])
    route_methods: dict[str, set[str]] = {}
    for route in public.routes:
        if hasattr(route, "methods"):
            route_methods.setdefault(route.path, set()).update(route.methods)

    assert route_methods["/manual-entries"] == {"GET", "POST"}
    assert route_methods["/manual-entries/{entry_id}"] == {"DELETE", "PATCH"}
    assert route_methods["/manual-entries/{entry_id}/weather"] == {"DELETE"}
    assert route_methods["/manual-entries/assets"] == {"POST"}


class _EntryStore:
    def __init__(self, entry: ManualEntry) -> None:
        self.entry = copy.deepcopy(entry)
        self.create_calls = 0
        self.update_calls = 0
        self.finalize_delete_calls = 0
        self.fail_reserve_count = 0
        self.fail_reserve_after_commit_count = 0
        self.reserve_false_count = 0
        self.fail_complete_count = 0
        self.fail_complete_after_commit_count = 0
        self.complete_false_count = 0
        self.fail_replace_count = 0
        self.fail_replace_after_commit_count = 0
        self.fail_delete_request_count = 0
        self.fail_delete_request_after_commit_count = 0
        self.fail_finalize_delete_count = 0
        self.fail_finalize_delete_after_commit_count = 0
        self.fail_weather_count = 0
        self.list_include_deleted: bool | None = None

    async def create(self, entry: ManualEntry) -> str:
        await asyncio.sleep(0)
        self.create_calls += 1
        self.entry = copy.deepcopy(entry)
        return entry.entry_id

    async def get(self, entry_id: str):
        await asyncio.sleep(0)
        return copy.deepcopy(self.entry) if entry_id == self.entry.entry_id else None

    async def update(self, entry_id: str, **changes) -> bool:
        await asyncio.sleep(0)
        assert entry_id == self.entry.entry_id
        expected_l1_event_id = changes.pop("expected_l1_event_id")
        if (
            self.entry.deleted_at is not None
            or self.entry.delete_requested_at is not None
            or self.entry.pending_l1_event_id is not None
            or self.entry.l1_event_id != expected_l1_event_id
        ):
            return False
        clear_weather = bool(changes.pop("clear_weather"))
        self.update_calls += 1
        for field, value in changes.items():
            if field == "clear_body_doc":
                if value:
                    self.entry.body_doc = None
                continue
            if value is None:
                continue
            target = "attachments" if field == "attachments" else field
            if field in {"mood", "location_label"}:
                value = value or None
            setattr(self.entry, target, copy.deepcopy(value))
        if clear_weather:
            self.entry.weather = None
        return True

    async def set_weather(self, entry_id: str, weather) -> bool:
        assert entry_id == self.entry.entry_id
        if self.fail_weather_count:
            self.fail_weather_count -= 1
            raise RuntimeError("weather persistence failed")
        if (
            self.entry.deleted_at is not None
            or self.entry.delete_requested_at is not None
            or self.entry.pending_l1_event_id is not None
        ):
            return False
        self.entry.weather = copy.deepcopy(weather)
        return True

    async def reserve_l1_projection(
        self,
        entry_id: str,
        event_id: str,
        *,
        expected_previous_event_id: str | None,
    ) -> bool:
        await asyncio.sleep(0)
        assert entry_id == self.entry.entry_id
        if self.fail_reserve_count:
            self.fail_reserve_count -= 1
            raise sqlite3.OperationalError("database is locked")
        if self.reserve_false_count:
            self.reserve_false_count -= 1
            return False
        if (
            self.entry.deleted_at is not None
            or self.entry.delete_requested_at is not None
            or self.entry.l1_event_id != expected_previous_event_id
            or (
                self.entry.pending_l1_event_id is not None
                and (
                    self.entry.pending_l1_event_id != event_id
                    or self.entry.pending_l1_predecessor_event_id != expected_previous_event_id
                )
            )
        ):
            return False
        self.entry.pending_l1_event_id = event_id
        self.entry.pending_l1_predecessor_event_id = expected_previous_event_id
        if self.fail_reserve_after_commit_count:
            self.fail_reserve_after_commit_count -= 1
            raise RuntimeError("reserve response lost after commit")
        return True

    async def replace_and_reserve_l1_projection(
        self,
        entry: ManualEntry,
        event_id: str,
        *,
        expected_previous_event_id: str | None,
    ) -> bool:
        await asyncio.sleep(0)
        assert entry.entry_id == self.entry.entry_id
        if self.fail_replace_count:
            self.fail_replace_count -= 1
            raise sqlite3.OperationalError("database is locked")
        if (
            self.entry.deleted_at is not None
            or self.entry.delete_requested_at is not None
            or self.entry.l1_event_id != expected_previous_event_id
            or (
                self.entry.pending_l1_event_id is not None
                and (
                    self.entry.pending_l1_event_id != event_id
                    or self.entry.pending_l1_predecessor_event_id != expected_previous_event_id
                )
            )
        ):
            return False
        linked_event_id = self.entry.l1_event_id
        self.entry = copy.deepcopy(entry)
        self.entry.l1_event_id = linked_event_id
        self.entry.pending_l1_event_id = event_id
        self.entry.pending_l1_predecessor_event_id = expected_previous_event_id
        self.update_calls += 1
        if self.fail_replace_after_commit_count:
            self.fail_replace_after_commit_count -= 1
            raise RuntimeError("replace response lost after commit")
        return True

    async def complete_l1_projection(
        self,
        entry_id: str,
        event_id: str,
        *,
        expected_previous_event_id: str | None,
    ) -> bool:
        await asyncio.sleep(0)
        assert entry_id == self.entry.entry_id
        if self.fail_complete_count:
            self.fail_complete_count -= 1
            raise RuntimeError("complete failed")
        if self.complete_false_count:
            self.complete_false_count -= 1
            return False
        if (
            self.entry.deleted_at is not None
            or self.entry.delete_requested_at is not None
            or self.entry.l1_event_id != expected_previous_event_id
            or self.entry.pending_l1_event_id != event_id
            or self.entry.pending_l1_predecessor_event_id != expected_previous_event_id
        ):
            return False
        self.entry.l1_event_id = event_id
        self.entry.pending_l1_event_id = None
        self.entry.pending_l1_predecessor_event_id = None
        if self.fail_complete_after_commit_count:
            self.fail_complete_after_commit_count -= 1
            raise RuntimeError("complete response lost after commit")
        return True

    async def request_delete(self, entry_id: str, *, requested_at: float) -> bool:
        await asyncio.sleep(0)
        assert entry_id == self.entry.entry_id
        if self.fail_delete_request_count:
            self.fail_delete_request_count -= 1
            raise RuntimeError("delete request failed")
        if self.entry.deleted_at is not None:
            return False
        if self.entry.delete_requested_at is None:
            self.entry.delete_requested_at = requested_at
        if self.fail_delete_request_after_commit_count:
            self.fail_delete_request_after_commit_count -= 1
            raise RuntimeError("delete request response lost after commit")
        return True

    async def finalize_delete(self, entry_id: str, *, deleted_at: float) -> bool:
        await asyncio.sleep(0)
        assert entry_id == self.entry.entry_id
        if self.fail_finalize_delete_count:
            self.fail_finalize_delete_count -= 1
            raise RuntimeError("delete finalize failed")
        if self.entry.deleted_at is not None or self.entry.delete_requested_at is None:
            return False
        self.finalize_delete_calls += 1
        self.entry.deleted_at = deleted_at
        self.entry.l1_event_id = None
        self.entry.pending_l1_event_id = None
        self.entry.pending_l1_predecessor_event_id = None
        self.entry.delete_requested_at = None
        if self.fail_finalize_delete_after_commit_count:
            self.fail_finalize_delete_after_commit_count -= 1
            raise RuntimeError("delete finalize response lost after commit")
        return True

    async def list_window(
        self,
        *,
        time_start: float,
        time_end: float,
        include_deleted: bool,
        limit: int,
    ):
        _ = time_start, time_end, limit
        self.list_include_deleted = include_deleted
        if self.entry.deleted_at is not None and not include_deleted:
            return []
        if (
            not include_deleted
            and self.entry.pending_l1_event_id is not None
            and self.entry.pending_l1_predecessor_event_id is not None
        ):
            return []
        return [copy.deepcopy(self.entry)]


class _L1View:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {"event-old": {"event_id": "event-old", "deleted_at": None}}

    async def get_event(self, event_id: str):
        await asyncio.sleep(0)
        event = self.events.get(event_id)
        return copy.deepcopy(event) if event is not None else None

    async def get_raw_event_active_states(self, event_ids: list[str]):
        return {
            event_id: event["deleted_at"] is None
            for event_id in event_ids
            if (event := self.events.get(event_id)) is not None
        }


class _Memory:
    def __init__(self) -> None:
        self._operation_barrier = AsyncOperationBarrier()
        self._clear_epoch = 0
        self._clear_request_count = 0
        self._write_lock = asyncio.Lock()
        self.l1 = _L1View()
        self.fail_forget_count = 0
        self.forgotten: list[tuple[str, str]] = []
        self.source_item_block_flags: list[tuple[str, str, bool]] = []
        self.tombstones: set[str] = set()

    def memory_operation_guard(self):
        return self._operation_barrier.operation()

    def memory_operation_epoch(self) -> int:
        return self._clear_epoch

    def memory_clear_in_progress(self) -> bool:
        return self._clear_request_count > 0

    @asynccontextmanager
    async def governed_l1_write_guard(self):
        async with self.memory_operation_guard():
            async with self._write_lock:
                yield

    async def governed_l1_event_rejection_reason(self, _event):
        return None

    async def governed_l1_event_rejection_reason_guarded(self, _event):
        return None

    async def store_governed_l1_event_under_write_lock(self, event) -> str:
        self.l1.events.setdefault(
            event.event_id,
            {"event_id": event.event_id, "deleted_at": None},
        )
        return event.event_id

    async def forget_known_source_events(
        self,
        event_ids,
        *,
        reason: str,
        block_source_item: bool = True,
    ) -> int:
        await asyncio.sleep(0)
        if self.fail_forget_count:
            self.fail_forget_count -= 1
            raise RuntimeError("forget failed")
        changed = 0
        for event_id in dict.fromkeys(event_ids):
            event = self.l1.events.get(event_id)
            if event is not None and event["deleted_at"] is None:
                event["deleted_at"] = 200.0
                changed += 1
            self.tombstones.add(event_id)
            self.forgotten.append((event_id, reason))
            self.source_item_block_flags.append((event_id, reason, block_source_item))
        return changed


class _Projector:
    def __init__(self, memory: _Memory) -> None:
        self.memory = memory
        self.fail_count = 0
        self.calls: list[tuple[str | None, str, object]] = []
        self._ids_by_key: dict[str, str] = {}
        self.project_started: asyncio.Event | None = None
        self.project_continue: asyncio.Event | None = None
        self.fail_ensure_count = 0

    def event_id_for(
        self,
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str:
        key = json.dumps(
            [predecessor_event_id, entry.body, entry.weather],
            ensure_ascii=False,
            sort_keys=True,
        )
        return self._ids_by_key.setdefault(key, f"event-new-{len(self._ids_by_key) + 1}")

    def governed_write_guard(self):
        return self.memory.governed_l1_write_guard()

    async def ensure_projectable(
        self,
        _entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> None:
        _ = predecessor_event_id
        if self.fail_ensure_count:
            self.fail_ensure_count -= 1
            raise RuntimeError("governance lookup failed")

    async def ensure_projectable_guarded(
        self,
        _entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> None:
        _ = predecessor_event_id

    async def project_current(
        self,
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str:
        await asyncio.sleep(0)
        self.calls.append((predecessor_event_id, entry.body, copy.deepcopy(entry.weather)))
        if self.project_started is not None:
            self.project_started.set()
        if self.project_continue is not None:
            await self.project_continue.wait()
        if self.fail_count:
            self.fail_count -= 1
            raise RuntimeError("projection failed")
        event_id = self.event_id_for(
            entry,
            predecessor_event_id=predecessor_event_id,
        )
        self.memory.l1.events.setdefault(event_id, {"event_id": event_id, "deleted_at": None})
        return event_id

    async def project_current_guarded(
        self,
        entry: ManualEntry,
        *,
        predecessor_event_id: str | None,
    ) -> str:
        return await self.project_current(
            entry,
            predecessor_event_id=predecessor_event_id,
        )


def _install_stores(monkeypatch, entry: ManualEntry, *, weather_fetcher=None):
    store = _EntryStore(entry)
    memory = _Memory()
    if entry.l1_event_id and entry.l1_event_id != "event-old":
        memory.l1.events[entry.l1_event_id] = {
            "event_id": entry.l1_event_id,
            "deleted_at": None,
        }
    projector = _Projector(memory)
    monkeypatch.setattr(
        routes,
        "_resolve_stores",
        lambda: (store, object(), projector, weather_fetcher, None, memory),
    )
    return store, memory, projector


def _install_stores_with_assets(
    monkeypatch,
    entry: ManualEntry,
    *,
    asset_store: ManualEntryAssetStore,
):
    store = _EntryStore(entry)
    memory = _Memory()
    projector = _Projector(memory)
    monkeypatch.setattr(
        routes,
        "_resolve_stores",
        lambda: (store, asset_store, projector, None, None, memory),
    )
    return store, memory, projector


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("upload", "create", "update"))
async def test_manual_entry_writes_fail_closed_while_memory_clear_is_pending(
    monkeypatch,
    operation,
):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    memory._clear_request_count = 1

    with pytest.raises(HTTPException) as error:
        if operation == "upload":
            await routes.upload_manual_entry_asset(
                UploadFile(filename="private.png", file=io.BytesIO(b"private"))
            )
        elif operation == "create":
            await routes.create_manual_entry(
                routes.ManualEntryCreateBody(
                    entry_id="me-during-clear",
                    body="private draft",
                )
            )
        else:
            await routes.update_manual_entry(
                "manual-1",
                routes.ManualEntryUpdateBody(body="private update"),
            )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "memory_clear_in_progress"
    assert store.create_calls == 0
    assert store.update_calls == 0


@pytest.mark.asyncio
async def test_manual_entry_write_does_not_resume_after_crossing_clear_epoch(
    monkeypatch,
):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    guard_entered = asyncio.Event()
    continue_guard = asyncio.Event()

    @asynccontextmanager
    async def delayed_guard():
        guard_entered.set()
        await continue_guard.wait()
        yield

    monkeypatch.setattr(memory, "memory_operation_guard", delayed_guard)
    request = asyncio.create_task(
        routes.create_manual_entry(
            routes.ManualEntryCreateBody(
                entry_id="me-stale-after-clear",
                body="private draft",
            )
        )
    )
    await guard_entered.wait()
    memory._clear_epoch += 1
    continue_guard.set()

    with pytest.raises(HTTPException) as error:
        await request

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "memory_clear_in_progress"
    assert store.create_calls == 0


@pytest.mark.asyncio
async def test_update_cleanup_failure_hides_reserved_replacement_and_allows_retry(
    monkeypatch,
):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    memory.fail_forget_count = 1
    body = routes.ManualEntryUpdateBody(body="after")

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry("manual-1", body)

    assert error.value.status_code == 503
    assert store.entry.body == "after"
    assert store.entry.pending_l1_event_id is not None
    assert store.update_calls == 1
    assert len(projector.calls) == 1
    assert memory.l1.events["event-old"]["deleted_at"] is None
    assert await routes.list_manual_entries(time_start=0, time_end=1000, limit=500) == {"items": []}

    result = await routes.update_manual_entry("manual-1", body)

    assert result["body"] == "after"
    assert store.entry.l1_event_id.startswith("event-new-")
    assert memory.l1.events["event-old"]["deleted_at"] is not None
    assert memory.forgotten == [("event-old", "manual_entry_update_repair")]
    assert memory.source_item_block_flags == [("event-old", "manual_entry_update_repair", False)]


@pytest.mark.asyncio
async def test_update_reservation_failure_leaves_old_source_and_projection(
    monkeypatch,
):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    store.fail_replace_count = 1

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="after"),
        )

    assert error.value.status_code == 503
    assert store.entry.body == "before"
    assert store.entry.pending_l1_event_id is None
    assert memory.l1.events["event-old"]["deleted_at"] is None
    assert projector.calls == []


@pytest.mark.asyncio
async def test_update_recovers_replacement_reservation_commit_ack_loss(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    store.fail_replace_after_commit_count = 1

    result = await routes.update_manual_entry(
        "manual-1",
        routes.ManualEntryUpdateBody(body="after"),
    )

    assert result["body"] == "after"
    assert result["l1_event_id"].startswith("event-new-")
    assert store.entry.pending_l1_event_id is None
    assert memory.l1.events["event-old"]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_update_rejects_empty_final_entry_before_forgetting(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="   ", attachment_refs=[]),
        )

    assert error.value.status_code == 400
    assert memory.forgotten == []
    assert store.update_calls == 0
    assert projector.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_ref",
    [
        "manual-entry-asset:///tmp/private.jpg",
        f"manual-entry-asset://{'a' * 64}.jpg",
    ],
)
async def test_create_rejects_forged_or_missing_attachment_refs(
    monkeypatch,
    tmp_path,
    asset_ref,
):
    asset_store = ManualEntryAssetStore(media_root=tmp_path)
    store, memory, projector = _install_stores_with_assets(
        monkeypatch,
        _entry(),
        asset_store=asset_store,
    )

    with pytest.raises(HTTPException) as error:
        await routes.create_manual_entry(
            routes.ManualEntryCreateBody(
                entry_id="me-create-invalid-asset",
                body="entry",
                attachment_refs=[asset_ref],
            )
        )

    assert error.value.status_code == 400
    assert store.create_calls == 0
    assert memory.forgotten == []
    assert projector.calls == []


@pytest.mark.asyncio
async def test_create_completion_failure_keeps_owned_projection_discoverable_and_deletable(
    monkeypatch,
):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    store.fail_complete_count = 1

    result = await routes.create_manual_entry(
        routes.ManualEntryCreateBody(
            entry_id="me-create-completion-failure",
            body="new entry",
        )
    )

    assert result["memory_status"] == "pending"
    entry_id = store.entry.entry_id
    pending_event_id = store.entry.pending_l1_event_id
    assert entry_id.startswith("me-")
    assert pending_event_id is not None
    assert store.entry.l1_event_id is None
    assert memory.l1.events[pending_event_id]["deleted_at"] is None

    listed = await routes.list_manual_entries(time_start=0, time_end=10**12, limit=500)
    assert [item["entry_id"] for item in listed["items"]] == [entry_id]

    assert await routes.delete_manual_entry(entry_id) == {"ok": True}
    assert memory.l1.events[pending_event_id]["deleted_at"] is not None
    assert store.entry.deleted_at is not None


@pytest.mark.asyncio
async def test_create_recovers_reservation_and_completion_commit_ack_loss(monkeypatch):
    store, _, _ = _install_stores(monkeypatch, _entry())
    store.fail_reserve_after_commit_count = 1
    store.fail_complete_after_commit_count = 1

    result = await routes.create_manual_entry(
        routes.ManualEntryCreateBody(
            entry_id="me-create-ack-loss",
            body="new entry",
        )
    )

    assert result["l1_event_id"] is not None
    assert store.entry.l1_event_id == result["l1_event_id"]
    assert store.entry.pending_l1_event_id is None


@pytest.mark.asyncio
async def test_create_database_lock_writes_no_l1_and_noop_update_repairs(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    store.fail_reserve_count = 1

    create_result = await routes.create_manual_entry(
        routes.ManualEntryCreateBody(
            entry_id="me-create-reserve-failure",
            body="new entry",
        )
    )

    assert create_result["memory_status"] == "pending"
    assert store.entry.l1_event_id is None
    assert store.entry.pending_l1_event_id is None
    assert projector.calls == []

    result = await routes.update_manual_entry(
        store.entry.entry_id,
        routes.ManualEntryUpdateBody(),
    )

    assert result["l1_event_id"] is not None
    assert memory.l1.events[result["l1_event_id"]]["deleted_at"] is None


@pytest.mark.asyncio
async def test_create_complete_false_is_repaired_without_a_second_l1_row(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    store.complete_false_count = 1

    create_result = await routes.create_manual_entry(
        routes.ManualEntryCreateBody(
            entry_id="me-create-complete-false",
            body="new entry",
        )
    )

    assert create_result["memory_status"] == "pending"
    pending_event_id = store.entry.pending_l1_event_id
    assert pending_event_id is not None
    assert list(memory.l1.events).count(pending_event_id) == 1

    result = await routes.update_manual_entry(
        store.entry.entry_id,
        routes.ManualEntryUpdateBody(),
    )

    assert result["l1_event_id"] == pending_event_id
    assert store.entry.pending_l1_event_id is None
    assert list(memory.l1.events).count(pending_event_id) == 1


@pytest.mark.asyncio
async def test_create_retry_reuses_client_identity_without_duplicate_source(
    monkeypatch,
    tmp_path,
):
    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    store = ManualEntryStore(db_path=str(memory_db))
    assets = ManualEntryAssetStore(media_root=tmp_path / "media")
    memory = _Memory()
    projector = _Projector(memory)
    projector.fail_count = 1
    monkeypatch.setattr(
        routes,
        "_resolve_stores",
        lambda: (store, assets, projector, None, None, memory),
    )
    body = routes.ManualEntryCreateBody(
        entry_id="me-stable-create-retry",
        body="same user note",
    )

    first_result = await routes.create_manual_entry(body)
    assert first_result["memory_status"] == "pending"
    first = await store.get(body.entry_id)
    assert first is not None
    first_event_at = first.event_at

    result = await routes.create_manual_entry(body)
    assert result["entry_id"] == body.entry_id
    assert result["event_at"] == first_event_at
    assert result["memory_status"] == "ready"

    recovery = ManualEntryRecoveryService(
        store=store,
        projector=projector,
        memory=memory,
        interval_seconds=0,
    )
    startup = await recovery.start()
    entries = await store.list_window(time_start=0, time_end=10**12)
    assert startup.skipped == 1
    assert [entry.entry_id for entry in entries] == [body.entry_id]

    with pytest.raises(HTTPException) as conflict:
        await routes.create_manual_entry(
            routes.ManualEntryCreateBody(
                entry_id=body.entry_id,
                body="different note",
            )
        )
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_create_forget_between_l1_write_and_link_returns_terminal_conflict(
    monkeypatch,
    tmp_path,
):
    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    continue_completion = asyncio.Event()
    try:
        store = ManualEntryStore(db_path=str(memory_db))
        memory.register_source_forget_owner(
            "manual_entry",
            ManualEntrySourceForgetOwner(store=store),
        )
        assets = ManualEntryAssetStore(media_root=tmp_path / "media")
        projector = ManualEntryL1Projector(memory=memory)
        completion_started = asyncio.Event()
        original_complete = store.complete_l1_projection

        async def pause_completion(*args, **kwargs):
            completion_started.set()
            await continue_completion.wait()
            return await original_complete(*args, **kwargs)

        monkeypatch.setattr(store, "complete_l1_projection", pause_completion)
        monkeypatch.setattr(
            routes,
            "_resolve_stores",
            lambda: (store, assets, projector, None, None, memory),
        )
        body = routes.ManualEntryCreateBody(
            entry_id="me-forgotten-before-link",
            body="private source",
            event_at=1_000.0,
        )
        create_task = asyncio.create_task(routes.create_manual_entry(body))
        await asyncio.wait_for(completion_started.wait(), timeout=10.0)
        pending = await store.get(body.entry_id)
        assert pending is not None
        assert pending.pending_l1_event_id is not None

        assert (
            await memory.forget_known_source_events(
                [pending.pending_l1_event_id],
                reason="external_user_forget",
                block_source_item=True,
            )
            == 1
        )
        continue_completion.set()

        with pytest.raises(HTTPException) as first_error:
            await create_task
        assert first_error.value.status_code == 409
        assert first_error.value.detail == {
            "code": "manual_entry_memory_forgotten",
            "reason": "source_reference",
            "retry_as_new": True,
            "source_preserved": False,
            "message": (
                "This occurrence is covered by a durable memory-forget rule"
            ),
        }

        with pytest.raises(HTTPException) as retry_error:
            await routes.create_manual_entry(body)
        assert retry_error.value.status_code == 409
        assert retry_error.value.detail == first_error.value.detail
    finally:
        continue_completion.set()
        await memory.shutdown()


@pytest.mark.asyncio
async def test_weather_commit_ack_loss_projects_confirmed_snapshot(
    monkeypatch,
    tmp_path,
):
    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    try:
        store = ManualEntryStore(db_path=str(memory_db))
        memory.register_source_forget_owner(
            "manual_entry",
            ManualEntrySourceForgetOwner(store=store),
        )
        assets = ManualEntryAssetStore(media_root=tmp_path / "media")
        projector = ManualEntryL1Projector(memory=memory)
        weather = {"code": 65, "temp_c": 15.5}

        class _WeatherFetcher:
            async def fetch(self, **_kwargs):
                return dict(weather)

        original_set_weather = store.set_weather

        async def set_weather_then_lose_ack(entry_id, snapshot):
            assert await original_set_weather(entry_id, snapshot)
            raise sqlite3.OperationalError("weather commit acknowledgement lost")

        monkeypatch.setattr(store, "set_weather", set_weather_then_lose_ack)
        monkeypatch.setattr(
            routes,
            "_resolve_stores",
            lambda: (
                store,
                assets,
                projector,
                _WeatherFetcher(),
                None,
                memory,
            ),
        )

        result = await routes.create_manual_entry(
            routes.ManualEntryCreateBody(
                entry_id="me-weather-ack-loss",
                body="rain",
                event_at=1_000.0,
                location_lat=30.0,
                location_lng=120.0,
            )
        )

        assert result["memory_status"] == "ready"
        assert result["weather"] == weather
        stored = await store.get(result["entry_id"])
        assert stored is not None
        assert stored.weather == weather
        projected = await memory.l1.get_memory_event(result["l1_event_id"])
        assert projected is not None
        assert projected.metadata_json["manual_entry"]["weather"] == weather

        recovery = ManualEntryRecoveryService(
            store=store,
            projector=projector,
            memory=memory,
            interval_seconds=0,
        )
        stats = await recovery.start()
        assert stats.to_dict() == {
            "scanned": 1,
            "recovered": 0,
            "failed": 0,
            "skipped": 1,
        }
        after_recovery = await store.get(result["entry_id"])
        assert after_recovery is not None
        assert after_recovery.l1_event_id == result["l1_event_id"]
    finally:
        await memory.shutdown()


@pytest.mark.asyncio
async def test_update_validates_attachments_before_forgetting(monkeypatch, tmp_path):
    asset_store = ManualEntryAssetStore(media_root=tmp_path)
    store, memory, projector = _install_stores_with_assets(
        monkeypatch,
        _entry(),
        asset_store=asset_store,
    )

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(attachment_refs=["manual-entry-asset:///tmp/private.jpg"]),
        )

    assert error.value.status_code == 400
    assert store.update_calls == 0
    assert memory.forgotten == []
    assert projector.calls == []


@pytest.mark.asyncio
async def test_update_accepts_an_existing_uploaded_attachment(monkeypatch, tmp_path):
    asset_store = ManualEntryAssetStore(media_root=tmp_path)
    asset_ref = asset_store.store_bytes(b"uploaded", content_type="image/png")
    store, memory, _ = _install_stores_with_assets(
        monkeypatch,
        _entry(),
        asset_store=asset_store,
    )

    result = await routes.update_manual_entry(
        "manual-1",
        routes.ManualEntryUpdateBody(attachment_refs=[asset_ref]),
    )

    assert result["attachments"] == [asset_ref]
    assert store.update_calls == 1
    assert memory.forgotten == [("event-old", "manual_entry_update")]


@pytest.mark.asyncio
async def test_update_projection_failure_is_completed_by_idempotent_retry(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    projector.fail_count = 1
    body = routes.ManualEntryUpdateBody(body="after")

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry("manual-1", body)

    assert error.value.status_code == 503
    assert store.entry.body == "after"
    assert store.entry.l1_event_id == "event-old"
    assert memory.l1.events["event-old"]["deleted_at"] is None

    result = await routes.update_manual_entry("manual-1", body)

    assert result["l1_event_id"].startswith("event-new-")
    assert store.update_calls == 1
    assert memory.forgotten == [
        ("event-old", "manual_entry_update_repair"),
    ]


@pytest.mark.asyncio
async def test_update_link_failure_reuses_unlinked_projection_on_retry(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    store.fail_complete_count = 1
    body = routes.ManualEntryUpdateBody(body="after")

    with pytest.raises(HTTPException) as error:
        await routes.update_manual_entry("manual-1", body)

    assert error.value.status_code == 503
    assert store.entry.l1_event_id == "event-old"
    unlinked_ids = [event_id for event_id in memory.l1.events if event_id != "event-old"]
    assert len(unlinked_ids) == 1

    result = await routes.update_manual_entry("manual-1", body)

    assert result["l1_event_id"] == unlinked_ids[0]
    assert [event_id for event_id in memory.l1.events if event_id != "event-old"] == unlinked_ids


@pytest.mark.asyncio
async def test_delete_after_link_failure_removes_the_unlinked_projection(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    store.fail_complete_count = 1
    body = routes.ManualEntryUpdateBody(body="after")
    with pytest.raises(HTTPException):
        await routes.update_manual_entry("manual-1", body)
    unlinked_id = next(event_id for event_id in memory.l1.events if event_id != "event-old")

    assert await routes.delete_manual_entry("manual-1") == {"ok": True}

    assert memory.l1.events[unlinked_id]["deleted_at"] is not None
    assert store.entry.deleted_at is not None


@pytest.mark.asyncio
async def test_concurrent_updates_leave_only_the_linked_projection_active(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())

    await asyncio.gather(
        routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="first"),
        ),
        routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="second"),
        ),
    )

    active_ids = [
        event_id for event_id, event in memory.l1.events.items() if event["deleted_at"] is None
    ]
    assert active_ids == [store.entry.l1_event_id]
    assert store.entry.body == "second"


@pytest.mark.asyncio
async def test_concurrent_update_then_delete_cannot_revive_entry(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())

    update_task = asyncio.create_task(
        routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="after"),
        )
    )
    await asyncio.sleep(0)
    delete_task = asyncio.create_task(routes.delete_manual_entry("manual-1"))
    await asyncio.gather(update_task, delete_task)

    assert store.entry.deleted_at is not None
    assert all(event["deleted_at"] is not None for event in memory.l1.events.values())


@pytest.mark.asyncio
async def test_cross_process_projection_delete_race_compensates_late_l1_write(monkeypatch):
    store, memory, projector = _install_stores(
        monkeypatch,
        _entry(body="after"),
    )
    projector.project_started = asyncio.Event()
    projector.project_continue = asyncio.Event()
    entry = await store.get("manual-1")
    assert entry is not None

    projection_task = asyncio.create_task(
        routes._project_and_link(
            entry=entry,
            predecessor_event_id="event-old",
            store=store,
            projector=projector,
            memory=memory,
        )
    )
    await projector.project_started.wait()
    pending_event_id = store.entry.pending_l1_event_id
    assert pending_event_id is not None

    delete_result = await routes._delete_manual_entry_locked("manual-1")
    projector.fail_ensure_count = 1
    projector.project_continue.set()
    with pytest.raises(HTTPException) as error:
        await projection_task

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "manual_entry_memory_forgotten"
    assert error.value.detail["reason"] == "source_reference"
    assert error.value.detail["retry_as_new"] is True
    assert delete_result == {"ok": True}
    assert store.entry.deleted_at is not None
    assert memory.l1.events[pending_event_id]["deleted_at"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ("create", "update", "clear_weather"),
)
@pytest.mark.parametrize(
    "terminal_state",
    ("delete_requested", "deleted"),
)
async def test_terminal_write_retry_returns_forgotten_conflict(
    monkeypatch,
    operation,
    terminal_state,
):
    terminal_fields = (
        {"delete_requested_at": 200.0}
        if terminal_state == "delete_requested"
        else {"deleted_at": 200.0}
    )
    store, _, projector = _install_stores(
        monkeypatch,
        _entry(
            entry_id="me-terminal-retry",
            **terminal_fields,
        ),
    )
    projector.fail_ensure_count = 1

    with pytest.raises(HTTPException) as error:
        if operation == "create":
            await routes.create_manual_entry(
                routes.ManualEntryCreateBody(
                    entry_id="me-terminal-retry",
                    body="before",
                )
            )
        elif operation == "update":
            await routes.update_manual_entry(
                "me-terminal-retry",
                routes.ManualEntryUpdateBody(body="retry after lost response"),
            )
        else:
            await routes.clear_manual_entry_weather("me-terminal-retry")

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "manual_entry_memory_forgotten",
        "reason": "source_reference",
        "retry_as_new": True,
        "source_preserved": False,
        "message": (
            "This occurrence is covered by a durable memory-forget rule"
        ),
    }
    assert getattr(store.entry, f"{terminal_state}_at") == 200.0


@pytest.mark.asyncio
async def test_update_nonprojected_fields_does_not_rewrite_memory(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())

    result = await routes.update_manual_entry(
        "manual-1",
        routes.ManualEntryUpdateBody(
            user_pinned=True,
            body_doc={"type": "doc", "content": []},
        ),
    )

    assert result["user_pinned"] is True
    assert result["body_doc"] == {"type": "doc", "content": []}
    assert memory.forgotten == []
    assert projector.calls == []
    assert store.entry.l1_event_id == "event-old"


@pytest.mark.asyncio
async def test_delete_cleanup_failure_does_not_hide_entry_and_retry_finishes(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    memory.fail_forget_count = 1

    with pytest.raises(HTTPException) as error:
        await routes.delete_manual_entry("manual-1")

    assert error.value.status_code == 503
    assert store.entry.deleted_at is None
    assert store.entry.delete_requested_at is not None
    assert store.finalize_delete_calls == 0

    with pytest.raises(HTTPException) as update_error:
        await routes.update_manual_entry(
            "manual-1",
            routes.ManualEntryUpdateBody(body="must remain blocked"),
        )
    assert update_error.value.status_code == 409

    assert await routes.delete_manual_entry("manual-1") == {"ok": True}
    assert store.entry.deleted_at is not None
    assert store.finalize_delete_calls == 1
    assert memory.source_item_block_flags == [("event-old", "manual_entry_delete", True)]


@pytest.mark.asyncio
async def test_delete_retries_cleanup_for_an_already_hidden_entry(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry(deleted_at=150.0))

    result = await routes.delete_manual_entry("manual-1")

    assert result == {"ok": True, "already_deleted": True}
    assert memory.forgotten == [("event-old", "manual_entry_delete")]
    assert store.finalize_delete_calls == 0


@pytest.mark.asyncio
async def test_delete_recovers_request_and_finalize_commit_ack_loss(monkeypatch):
    store, memory, _ = _install_stores(monkeypatch, _entry())
    store.fail_delete_request_after_commit_count = 1
    store.fail_finalize_delete_after_commit_count = 1

    assert await routes.delete_manual_entry("manual-1") == {"ok": True}

    assert store.entry.deleted_at is not None
    assert store.finalize_delete_calls == 1
    assert memory.l1.events["event-old"]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_public_manual_entry_list_never_returns_deleted_rows(monkeypatch):
    store, _, _ = _install_stores(monkeypatch, _entry(deleted_at=150.0))

    result = await routes.list_manual_entries(time_start=0, time_end=1000, limit=500)

    assert result == {"items": []}
    assert store.list_include_deleted is False


@pytest.mark.asyncio
async def test_weather_clear_cleanup_failure_hides_reserved_change_then_retries(
    monkeypatch,
):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    memory.fail_forget_count = 1

    with pytest.raises(HTTPException) as error:
        await routes.clear_manual_entry_weather("manual-1")

    assert error.value.status_code == 503
    assert store.entry.weather is None
    assert store.entry.pending_l1_event_id is not None
    assert len(projector.calls) == 1

    result = await routes.clear_manual_entry_weather("manual-1")

    assert result["weather"] is None
    assert store.entry.weather is None
    assert store.entry.l1_event_id.startswith("event-new-")
    assert memory.source_item_block_flags == [("event-old", "manual_entry_weather_repair", False)]


@pytest.mark.asyncio
async def test_weather_projection_failure_is_repaired_when_clear_is_retried(monkeypatch):
    store, memory, projector = _install_stores(monkeypatch, _entry())
    projector.fail_count = 1

    with pytest.raises(HTTPException):
        await routes.clear_manual_entry_weather("manual-1")

    assert store.entry.weather is None
    assert store.entry.l1_event_id == "event-old"

    result = await routes.clear_manual_entry_weather("manual-1")

    assert result["weather"] is None
    assert result["l1_event_id"].startswith("event-new-")
    assert memory.l1.events["event-old"]["deleted_at"] is not None


@pytest.mark.asyncio
async def test_weather_clear_persistence_failure_preserves_value_for_retry(monkeypatch):
    store, _, _ = _install_stores(monkeypatch, _entry())
    store.fail_replace_count = 1

    with pytest.raises(HTTPException) as error:
        await routes.clear_manual_entry_weather("manual-1")

    assert error.value.status_code == 503
    assert store.entry.weather == {"code": 1, "temp_c": 20.0}

    result = await routes.clear_manual_entry_weather("manual-1")
    assert result["weather"] is None


@pytest.mark.asyncio
async def test_event_time_update_persists_and_projects_one_weather_snapshot(monkeypatch):
    class _WeatherFetcher:
        async def fetch(self, **_kwargs):
            return {"code": 9, "temp_c": 30.0}

    store, _, projector = _install_stores(
        monkeypatch,
        _entry(location_lat=30.0, location_lng=120.0),
        weather_fetcher=_WeatherFetcher(),
    )
    result = await routes.update_manual_entry(
        "manual-1",
        routes.ManualEntryUpdateBody(event_at=1000.0),
    )

    assert result["event_at"] == 1000.0
    assert result["weather"] == {"code": 9, "temp_c": 30.0}
    assert store.entry.weather == {"code": 9, "temp_c": 30.0}
    assert projector.calls[-1][2] == {"code": 9, "temp_c": 30.0}


@pytest.mark.asyncio
async def test_real_failed_completion_delete_removes_l1_through_l4(
    monkeypatch,
    tmp_path,
):
    memory_db = tmp_path / "memory.db"
    await apply_memory_shared_schema(str(memory_db))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(memory_db),
        enable_l0=False,
        enable_l1=True,
        enable_l2=True,
        enable_l3=True,
        enable_l4=True,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
            enable_l3_llm_summary=False,
            async_embeddings=False,
        ),
    )
    await memory.initialize()
    try:
        assert memory.l1 is not None
        assert memory.l2 is not None
        assert memory.l3 is not None
        assert memory.l4 is not None
        store = ManualEntryStore(db_path=str(memory_db))
        memory.register_source_forget_owner(
            "manual_entry",
            ManualEntrySourceForgetOwner(store=store),
        )
        assets = ManualEntryAssetStore(media_root=tmp_path / "media")
        projector = ManualEntryL1Projector(memory=memory)
        original_complete = store.complete_l1_projection
        fail_complete = True

        async def complete_once(*args, **kwargs):
            nonlocal fail_complete
            if fail_complete:
                fail_complete = False
                raise sqlite3.OperationalError("database is locked")
            return await original_complete(*args, **kwargs)

        monkeypatch.setattr(store, "complete_l1_projection", complete_once)
        monkeypatch.setattr(
            routes,
            "_resolve_stores",
            lambda: (store, assets, projector, None, None, memory),
        )

        create_result = await routes.create_manual_entry(
            routes.ManualEntryCreateBody(
                entry_id="me-private-manual-source",
                body="private manual source",
            )
        )
        assert create_result["memory_status"] == "pending"

        entries = await store.list_window(time_start=0, time_end=10**12)
        assert len(entries) == 1
        source = entries[0]
        event_id = source.pending_l1_event_id
        assert event_id is not None
        assertion_id = await memory.l2.upsert_assertion_candidate(
            {
                "entity_id": "user:default",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "manual_private_preference",
                "trait_value": "private manual source",
                "confidence_score": 0.9,
                "evidence_events": [event_id],
                "volatility_index": 0.1,
                "source_domain": "manual_entry",
                "inference_depth": "explicit",
                "validation_state": "stable",
                "first_inferred_at": source.event_at,
                "last_validated_at": source.event_at,
                "temporal_scope": "persistent",
            }
        )
        summary = await memory.l3.upsert_candidate(
            candidate=L3Candidate(
                summary_type="thematic",
                summary_category="topic",
                content="private manual summary",
                source_event_ids=[event_id],
                insight_key="manual-private-summary",
            )
        )
        preference_id = await memory.l4.record_task_preference(
            user_id="user:default",
            persona_id="seven",
            task_category="manual-entry-test",
            preference="private manual preference",
            evidence_text="private manual source",
            confidence=0.9,
            turn_id=event_id,
        )
        assert preference_id is not None

        assert await routes.delete_manual_entry(source.entry_id) == {"ok": True}

        l1_event = await memory.l1.get_event(event_id)
        assert l1_event is not None and l1_event["deleted_at"] is not None
        assertion = await memory.l2.get_tom_assertion(assertion_id=assertion_id)
        assert assertion is not None and assertion["status"] == "archived"
        assert await memory.l3.get_summary_by_id(summary["summary_id"]) is None
        assert (
            await memory.l4.get_task_preferences(
                user_id="user:default",
                task_category="manual-entry-test",
            )
            == []
        )
        deleted_source = await store.get(source.entry_id)
        assert deleted_source is not None and deleted_source.deleted_at is not None
        assert deleted_source.pending_l1_event_id is None
    finally:
        await memory.shutdown()
