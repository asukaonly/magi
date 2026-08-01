"""Shared SQLite connection helpers and transaction utilities."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time
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

_JOURNAL_MODE_MAX_ATTEMPTS = 6
_JOURNAL_MODE_RETRY_BASE_SECONDS = 0.01
_JOURNAL_MODE_RETRY_BUDGET_SECONDS = 1.0
_JOURNAL_MODE_BUSY_TIMEOUT_MS = 250


def get_sqlite_profile(profile: str | SqliteProfile = "default") -> SqliteProfile:
    """Resolve a named SQLite profile."""
    if isinstance(profile, SqliteProfile):
        return profile
    try:
        return SQLITE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown SQLite profile: {profile}") from exc


def _is_sqlite_lock_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _journal_mode_retry_delay(attempt: int) -> float:
    return _JOURNAL_MODE_RETRY_BASE_SECONDS * (2**attempt)


async def _configure_async_journal_mode(
    db: aiosqlite.Connection,
    journal_mode: str,
) -> None:
    retry_deadline = time.monotonic() + _JOURNAL_MODE_RETRY_BUDGET_SECONDS
    for attempt in range(_JOURNAL_MODE_MAX_ATTEMPTS):
        try:
            await db.execute(f"PRAGMA journal_mode={journal_mode}")
            return
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_lock_error(exc) or attempt == _JOURNAL_MODE_MAX_ATTEMPTS - 1:
                raise
            delay = _journal_mode_retry_delay(attempt)
            if time.monotonic() + delay >= retry_deadline:
                raise
            await asyncio.sleep(delay)


def _configure_sync_journal_mode(
    cursor: sqlite3.Cursor,
    journal_mode: str,
) -> None:
    retry_deadline = time.monotonic() + _JOURNAL_MODE_RETRY_BUDGET_SECONDS
    for attempt in range(_JOURNAL_MODE_MAX_ATTEMPTS):
        try:
            cursor.execute(f"PRAGMA journal_mode={journal_mode}")
            return
        except sqlite3.OperationalError as exc:
            if not _is_sqlite_lock_error(exc) or attempt == _JOURNAL_MODE_MAX_ATTEMPTS - 1:
                raise
            delay = _journal_mode_retry_delay(attempt)
            if time.monotonic() + delay >= retry_deadline:
                raise
            time.sleep(delay)


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
    configuration_timeout_ms = min(
        max(0, int(resolved.busy_timeout_ms)),
        _JOURNAL_MODE_BUSY_TIMEOUT_MS,
    )
    await db.execute(f"PRAGMA busy_timeout = {configuration_timeout_ms}")
    await _configure_async_journal_mode(db, resolved.journal_mode)
    await db.execute(f"PRAGMA synchronous={resolved.synchronous}")
    await db.execute(f"PRAGMA foreign_keys = {1 if resolved.foreign_keys else 0}")
    await db.execute(f"PRAGMA busy_timeout = {int(resolved.busy_timeout_ms)}")
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
        configuration_timeout_ms = min(
            max(0, int(resolved.busy_timeout_ms)),
            _JOURNAL_MODE_BUSY_TIMEOUT_MS,
        )
        cursor.execute(f"PRAGMA busy_timeout = {configuration_timeout_ms}")
        _configure_sync_journal_mode(cursor, resolved.journal_mode)
        cursor.execute(f"PRAGMA synchronous={resolved.synchronous}")
        cursor.execute(f"PRAGMA foreign_keys = {1 if resolved.foreign_keys else 0}")
        cursor.execute(f"PRAGMA busy_timeout = {int(resolved.busy_timeout_ms)}")
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
    try:
        return configure_sqlite3(conn, profile=profile, use_row_factory=use_row_factory)
    except BaseException:
        conn.close()
        raise


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


async def secure_compact_sqlite(
    db_path: str | Path,
    *,
    profile: str | SqliteProfile = "default",
    timeout_seconds: float = 30.0,
) -> None:
    """Rewrite one SQLite file and truncate its WAL after sensitive deletion.

    Callers must quiesce writers before invoking this maintenance boundary.
    The pre-VACUUM checkpoint makes committed WAL content part of the database
    image, VACUUM rebuilds that image from live rows only, and the final
    checkpoint removes maintenance writes from the WAL sidecar.
    """

    expanded = Path(db_path).expanduser()
    if not expanded.exists():
        return

    async with sqlite_connection_async(
        expanded,
        profile=profile,
        timeout_seconds=timeout_seconds,
        use_row_factory=False,
    ) as db:
        await db.execute("PRAGMA secure_delete=ON")
        await _require_truncated_wal(db, db_path=expanded)
        await db.execute("VACUUM")
        await _require_truncated_wal(db, db_path=expanded)


async def _require_truncated_wal(
    db: aiosqlite.Connection,
    *,
    db_path: Path,
) -> None:
    cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    row = await cursor.fetchone()
    await cursor.close()
    if row is not None and int(row[0] or 0) != 0:
        raise RuntimeError(f"SQLite WAL is busy during secure compaction: {db_path}")


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
