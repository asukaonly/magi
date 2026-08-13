"""Focused persistence tests for bounded history-import identity reads."""

from __future__ import annotations

import pytest

from magi.memory.history_imports.store import (
    _load_reserved_session_prefixes,
    _load_source_identity_rows,
)


class _Cursor:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self._keys = keys

    async def __aenter__(self) -> "_Cursor":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None

    async def fetchall(self) -> list[dict[str, str]]:
        return [{"source_record_key": key} for key in self._keys]


class _Database:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def execute(self, query: str, parameters: tuple[str, ...]) -> _Cursor:
        assert "WHERE source_record_key IN" in query
        self.calls.append(parameters)
        return _Cursor(parameters)


@pytest.mark.asyncio
async def test_source_identity_rows_are_loaded_in_bounded_batches() -> None:
    database = _Database()
    keys = [f"record-{index}" for index in range(805)]

    loaded = await _load_source_identity_rows(
        database,
        [*keys, keys[0]],
    )

    assert [len(call) for call in database.calls] == [400, 400, 5]
    assert set(loaded) == set(keys)


class _PrefixDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def execute(self, query: str, parameters: tuple[object, ...]) -> _Cursor:
        assert "WITH requested(source_id, parsed_session_key)" in query
        self.calls.append(parameters)
        return _Cursor(())


@pytest.mark.asyncio
async def test_reserved_session_prefixes_are_loaded_in_bounded_batches() -> None:
    database = _PrefixDatabase()
    identities = [(f"source-{index}", f"session-{index}") for index in range(805)]

    loaded = await _load_reserved_session_prefixes(
        database,
        importer_plugin_id="archive",
        importer_id="export",
        importer_format_version="1",
        session_identities=[*identities, identities[0]],
    )

    assert loaded == {}
    assert [len(call) for call in database.calls] == [603, 603, 413]
