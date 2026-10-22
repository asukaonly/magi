"""External event replacement inside the journaled maintenance transaction."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...db.storage_bindings import StorageTarget
from ...utils.runtime import RuntimePaths
from ..l1.storage.snapshots import SqliteEventStateTransfer
from .errors import MemoryPortabilityError


class ExternalEventTarget(BaseModel):
    """Secret-free identity pinned before any external replacement is attempted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    target: StorageTarget
    center_id: str = Field(min_length=1, max_length=128)

    @field_validator("target")
    @classmethod
    def require_external_target(cls, target: StorageTarget) -> StorageTarget:
        if target.kind != "mysql":
            raise ValueError("External event restore requires a MySQL target")
        return target


def replace_external_events(
    paths: RuntimePaths, target: ExternalEventTarget, snapshot_path: Path,
) -> None:
    """Run in the filesystem transaction thread with a thread-owned connection.

    Startup recovery and live restore use the same synchronous journal engine.
    The temporary event loop owns and closes the async driver pool entirely in
    this thread; no runtime connection or loop is reused across shutdown.
    """
    asyncio.run(_replace_external_events(paths, target, snapshot_path))


async def _replace_external_events(
    paths: RuntimePaths, target: ExternalEventTarget, snapshot_path: Path,
) -> None:
    from ...bootstrap.portable_event_storage import open_portable_event_storage

    async with open_portable_event_storage(paths) as storage:
        if storage.target != target.target or storage.center_id != target.center_id:
            raise MemoryPortabilityError(
                "restore_storage_changed",
                "Event storage changed during restore. Restore its configuration before recovery.",
                status_code=409,
            )
        snapshot = await SqliteEventStateTransfer(str(snapshot_path)).export_state()
        await storage.transfer.import_state(snapshot, replace=True)
