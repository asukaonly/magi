"""Thread-safe native MySQL connections for chat reads and cleanup."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
import re
from typing import Any, Literal

from sqlalchemy import Connection, CursorResult, create_engine
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeoutError

from ....core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError
from ....db.mysql import MysqlSettings, mysql_connection_options
from ..statements import ChatSql, render_sql
from .database import MysqlChatRow, bind_parameters


@contextmanager
def _storage_errors() -> Iterator[None]:
    try:
        yield
    except IntegrityError as exc:
        raise PersistenceConflictError("Chat storage constraint rejected the write") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "args", (None,))[0] in {1644, 3819}:
            raise PersistenceConflictError("Chat write crossed a storage guard") from exc
        raise PersistenceUnavailableError("Chat storage operation could not be confirmed") from exc
    except PoolTimeoutError as exc:
        raise PersistenceUnavailableError("Chat storage connection is unavailable") from exc


class MysqlChatReadCursor:
    def __init__(self, result: CursorResult[Any]) -> None:
        self.rowcount = result.rowcount
        self._rows = [MysqlChatRow(row) for row in result] if result.returns_rows else []
        self._position = 0

    def fetchone(self) -> MysqlChatRow | None:
        if self._position >= len(self._rows):
            return None
        row = self._rows[self._position]
        self._position += 1
        return row

    def fetchall(self) -> list[MysqlChatRow]:
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows


class MysqlChatReadConnection:
    """Standalone reads release locks; snapshots and mutations are explicit."""

    def __init__(self, connection: Connection, center_id: str) -> None:
        self._connection = connection
        self._center_id = center_id
        self._mode: Literal["read", "write"] | None = None
        self._temporary_tables: set[str] = set()

    def _check_owner(self, *, lock: bool) -> None:
        suffix = " FOR UPDATE" if lock else ""
        owner = self._connection.exec_driver_sql("SELECT center_id FROM magi_chat_owner WHERE slot=1" + suffix).scalar_one_or_none()
        if owner != self._center_id:
            raise PersistenceConflictError("Chat storage belongs to another center")

    def verify_owner(self) -> None:
        with _storage_errors():
            self._check_owner(lock=False)
            self._connection.rollback()

    def begin_read(self) -> None:
        if self._mode is not None:
            raise RuntimeError("Chat snapshot cannot nest inside an active transaction")
        with _storage_errors():
            self._connection.rollback()
            self._connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self._connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            self._mode = "read"
            self._check_owner(lock=False)

    def begin_write(self) -> None:
        if self._mode == "write":
            return
        if self._mode == "read":
            raise RuntimeError("A chat read snapshot cannot become a write transaction")
        with _storage_errors():
            self._connection.rollback()
            self._connection.exec_driver_sql("START TRANSACTION")
            self._mode = "write"
            self._check_owner(lock=True)

    def execute(self, sql: str | ChatSql, parameters: Sequence[object] = ()) -> MysqlChatReadCursor:
        native = render_sql(sql, "mysql")
        verb = native.lstrip().split(None, 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE"}:
            self.begin_write()
        with _storage_errors():
            result = self._connection.exec_driver_sql(bind_parameters(native, len(parameters)), tuple(parameters))
            if native.lstrip().upper().startswith("INSERT IGNORE"):
                warnings = self._connection.exec_driver_sql("SHOW WARNINGS").all()
                if any(int(row[1]) not in {1062, 1287} for row in warnings):
                    raise PersistenceConflictError("Chat insert violated a storage constraint")
            temporary = re.match(r"\s*CREATE TEMPORARY TABLE IF NOT EXISTS ([A-Za-z0-9_]+)\s*\(", native)
            if temporary:
                self._temporary_tables.add(temporary[1])
            return MysqlChatReadCursor(result)

    def executemany(self, sql: str | ChatSql, parameters: Iterable[Sequence[object]]) -> MysqlChatReadCursor:
        result = None
        total = 0
        for values in parameters:
            result = self.execute(sql, values)
            total += result.rowcount
        if result is None:
            result = self.execute("SELECT 1 WHERE FALSE")
        result.rowcount = total
        return result

    def commit(self) -> None:
        with _storage_errors():
            try:
                self._connection.commit()
            finally:
                self._mode = None

    def rollback(self) -> None:
        with _storage_errors():
            try:
                self._connection.rollback()
            finally:
                self._mode = None

    def prepare_content_clear(self) -> None:
        """Server retention owns physical blocks; logical content is removed transactionally."""

    def compact_cleared_content(self) -> None:
        """Do not issue blocking server-wide compaction from a product operation."""
        if self._mode is not None:
            raise RuntimeError("Chat clear must commit before completing reclamation")

    def checkpoint_cleared_content(self) -> None:
        """InnoDB commit supplies durability; server logs remain operator-owned."""
        if self._mode is not None:
            raise RuntimeError("Chat clear must commit before completing durability")

    def close(self) -> None:
        try:
            with _storage_errors():
                self._connection.rollback()
                for table in sorted(self._temporary_tables):
                    self._connection.exec_driver_sql(f"DROP TEMPORARY TABLE `{table}`")
                self._temporary_tables.clear()
        except BaseException:
            self._connection.invalidate()
            raise
        finally:
            self._connection.close()
            self._mode = None


class MysqlChatReadDatabase:
    """Own a bounded synchronous pool used only by read-service worker threads."""

    def __init__(self, settings: MysqlSettings, *, center_id: str) -> None:
        if not center_id.strip():
            raise ValueError("Chat storage requires a center identity")
        url, connect_args = mysql_connection_options(settings, "pymysql")
        connect_args["write_timeout"] = settings.read_timeout_seconds
        self._engine = create_engine(url, pool_size=settings.pool_size, max_overflow=0,
            pool_timeout=5, pool_pre_ping=True, pool_recycle=300, hide_parameters=True,
            isolation_level="AUTOCOMMIT", connect_args=connect_args)
        self._center_id = center_id

    def is_present(self) -> bool:
        # Missing or unreachable native storage is an error, never an empty database.
        return True

    def open(self) -> MysqlChatReadConnection:
        with _storage_errors():
            connection = MysqlChatReadConnection(self._engine.connect(), self._center_id)
            try:
                connection.verify_owner()
                return connection
            except BaseException:
                connection.close()
                raise

    def close(self) -> None:
        self._engine.dispose()
