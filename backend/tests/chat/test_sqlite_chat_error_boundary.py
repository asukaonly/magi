"""Chat consumers receive owner failures without driver or SQL details."""

import sqlite3

import pytest

from magi.chat.storage.sqlite_database import SqliteChatDatabase, SqliteChatReadDatabase, SqliteChatReadCursor
from magi.core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError


@pytest.mark.parametrize("read", [False, True])
async def test_constraint_failure_rolls_back_and_hides_query_details(tmp_path, read):
    path = tmp_path / "chat.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, secret TEXT)")
    if read:
        connection = SqliteChatReadDatabase(path).open()
        try:
            connection.begin_write()
            connection.execute("INSERT INTO sample VALUES (1, 'private content')")
            with pytest.raises(PersistenceConflictError) as error:
                connection.execute("INSERT INTO sample VALUES (1, 'private retry')")
            connection.rollback()
        finally:
            connection.close()
    else:
        with pytest.raises(PersistenceConflictError) as error:
            async with SqliteChatDatabase(path).session() as connection:
                await connection.execute("INSERT INTO sample VALUES (1, 'private content')")
                await connection.execute("INSERT INTO sample VALUES (1, 'private retry')")
                await connection.commit()
    assert "private" not in str(error.value)
    assert isinstance(error.value.__cause__, sqlite3.IntegrityError)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM sample").fetchone() == (0,)


async def test_read_and_write_unavailability_is_explicit(tmp_path):
    path = tmp_path / "chat.db"
    async with SqliteChatDatabase(path).session() as connection:
        await connection.execute("CREATE TABLE sample(id INTEGER)")
        await connection.commit()
    with pytest.raises(PersistenceUnavailableError):
        async with SqliteChatDatabase(path).session() as connection:
            await connection.execute("SELECT * FROM missing")
    connection = SqliteChatReadDatabase(path).open()
    try:
        with pytest.raises(PersistenceUnavailableError):
            connection.execute("SELECT * FROM missing")
    finally:
        connection.close()


def test_lazy_cursor_failure_does_not_escape_driver_boundary():
    class BrokenCursor:
        rowcount = 0
        def fetchone(self):
            raise sqlite3.DatabaseError("Corrupt private database")
    cursor = SqliteChatReadCursor(BrokenCursor())
    with pytest.raises(PersistenceUnavailableError) as error:
        cursor.fetchone()
    assert "private" not in str(error.value)
