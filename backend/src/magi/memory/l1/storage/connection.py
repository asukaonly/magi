"""Keep driver failures inside the event persistence boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from ....core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError
from ....core.sqlite import sqlite_connection_async


@asynccontextmanager
async def event_connection(db_path: str, *, profile: str = "default") -> AsyncIterator[aiosqlite.Connection]:
    """Drain connection cleanup before exposing a driver-independent failure."""
    try:
        async with sqlite_connection_async(db_path, profile=profile) as db:
            yield db
    except aiosqlite.IntegrityError as exc:
        raise PersistenceConflictError("Memory event violates a persistence constraint") from exc
    except aiosqlite.Error as exc:
        raise PersistenceUnavailableError("Memory event storage did not confirm the operation") from exc
