"""Private portable containers for logical event state, independent of the live driver."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...db.runner import run_upgrade_database
from ..l1.storage.snapshots import SqliteEventStateTransfer
from ..l1.storage_snapshot import EventStorageSnapshot


async def materialize_event_snapshot(path: Path, snapshot: EventStorageSnapshot) -> None:
    """Create a fresh private SQLite container; never accept a live database path."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    path.chmod(0o600)
    await asyncio.to_thread(run_upgrade_database, "l1", path)
    await SqliteEventStateTransfer(str(path)).import_state(snapshot)
