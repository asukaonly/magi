"""Shared SQLite connection helpers and transaction utilities."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import AsyncIterator, Iterator

import aiosqlite


@dataclass(frozen=True, slots=True)
class SqliteProfile:
    """Connection policy for one SQLite workload."""

    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    busy_timeout_ms: int = 30_000
    foreign_keys: bool = True


DEFAULT_SQLITE_PROFILE = SqliteProfile()
SQLITE_PROFILES: dict[str, SqliteProfile] = {
    "default": DEFAULT_SQLITE_PROFILE,
    "hot_write": DEFAULT_SQLITE_PROFILE,
    "mixed": DEFAULT_SQLITE_PROFILE,
    "readonly": DEFAULT_SQLITE_PROFILE,
}


def get_sqlite_profile(profile: str | SqliteProfile = "default") -> SqliteProfile:
    """Resolve a named SQLite profile."""
    if isinstance(profile, SqliteProfile):
        return profile
    try:
        return SQLITE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown SQLite profile: {profile}") from exc


async def configure_aiosqlite(
    db: aiosqlite.Connection,
    *,
    profile: str | SqliteProfile = "default",
    use_row_factory: bool = True,
) -> aiosqlite.Connection:
    """Apply the shared SQLite policy to an async connection."""
    resolved = get_sqlite_profile(profile)
    if use_row_factory:
        db.row_factory = aiosqlite.Row
    await db.execute(f"PRAGMA journal_mode={resolved.journal_mode}")
    await db.execute(f"PRAGMA synchronous={resolved.synchronous}")
    await db.execute(f"PRAGMA busy_timeout = {int(resolved.busy_timeout_ms)}")
    await db.execute(f"PRAGMA foreign_keys = {1 if resolved.foreign_keys else 0}")
    return db


def configure_sqlite3(
    conn: sqlite3.Connection,
    *,
    profile: str | SqliteProfile = "default",
    use_row_factory: bool = True,
) -> sqlite3.Connection:
    """Apply the shared SQLite policy to a sync connection."""
    resolved = get_sqlite_profile(profile)
    if use_row_factory:
        conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(f"PRAGMA journal_mode={resolved.journal_mode}")
        cursor.execute(f"PRAGMA synchronous={resolved.synchronous}")
        cursor.execute(f"PRAGMA busy_timeout = {int(resolved.busy_timeout_ms)}")
        cursor.execute(f"PRAGMA foreign_keys = {1 if resolved.foreign_keys else 0}")
    finally:
        cursor.close()
    return conn


async def connect_aiosqlite(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
    use_row_factory: bool = True,
) -> aiosqlite.Connection:
    """Open an async SQLite connection with the shared policy applied."""
    expanded = Path(db_path).expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(expanded), timeout=timeout_seconds)
    try:
        return await configure_aiosqlite(
            db,
            profile=profile,
            use_row_factory=use_row_factory,
        )
    except BaseException:
        # Configuration performs worker-thread I/O. If the caller is cancelled
        # during that work, close the partially opened connection before the
        # event loop can go away.
        await asyncio.shield(db.close())
        raise


def connect_sqlite(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
    use_row_factory: bool = True,
) -> sqlite3.Connection:
    """Open a sync SQLite connection with the shared policy applied."""
    expanded = Path(db_path).expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(expanded), timeout=timeout_seconds)
    return configure_sqlite3(conn, profile=profile, use_row_factory=use_row_factory)


@asynccontextmanager
async def sqlite_connection_async(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
    use_row_factory: bool = True,
) -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async SQLite connection and always close it."""
    db = await connect_aiosqlite(
        db_path,
        profile=profile,
        timeout_seconds=timeout_seconds,
        use_row_factory=use_row_factory,
    )
    try:
        yield db
    finally:
        await db.close()


@asynccontextmanager
async def sqlite_transaction_async(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
    use_row_factory: bool = True,
) -> AsyncIterator[aiosqlite.Connection]:
    """Yield an async SQLite connection and commit or roll back automatically."""
    db = await connect_aiosqlite(
        db_path,
        profile=profile,
        timeout_seconds=timeout_seconds,
        use_row_factory=use_row_factory,
    )
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@contextmanager
def sqlite_transaction(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
    use_row_factory: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Yield a sync SQLite connection and commit or roll back automatically."""
    conn = connect_sqlite(
        db_path,
        profile=profile,
        timeout_seconds=timeout_seconds,
        use_row_factory=use_row_factory,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
