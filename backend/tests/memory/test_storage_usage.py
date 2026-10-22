"""Footprint reporting must not mistake inactive local files for remote storage."""

from pathlib import Path

import pytest

from magi.bootstrap.memory_storage_usage import compose_memory_storage_usage
from magi.config.memory_models import MemorySettings, VectorStorageSettings
from magi.config.storage_models import StructuredStorageSettings
from magi.db.mysql import MysqlSettings
from magi.memory.local_storage_usage import LocalMemoryStorageUsage
from magi.utils.runtime import RuntimePaths


@pytest.mark.parametrize("external", ["mysql", "chroma"])
def test_external_storage_has_no_complete_local_measurement(tmp_path, external):
    paths = RuntimePaths(tmp_path)
    paths.l1_memory_db_path.write_bytes(b"inactive local data")
    memory = MemorySettings(vector_storage=VectorStorageSettings(
        backend="chroma" if external == "chroma" else "sqlite_vec",
    ))
    structured = StructuredStorageSettings(
        memory_events="mysql" if external == "mysql" else "sqlite",
        mysql=MysqlSettings(host="localhost", database="memory", user="test", password_env="TEST_SECRET"),
    )
    assert compose_memory_storage_usage(paths, memory, structured) is None


async def test_local_measurement_includes_separate_vector_database_once(tmp_path):
    paths = RuntimePaths(tmp_path)
    paths.l1_memory_db_path.write_bytes(b"12")
    paths.memory_db_path.write_bytes(b"123")
    vectors = tmp_path / "vectors.db"
    vectors.write_bytes(b"12345")
    Path(f"{vectors}-wal").write_bytes(b"1234567")
    reader = compose_memory_storage_usage(
        paths, MemorySettings(vector_storage=VectorStorageSettings(sqlite_path=str(vectors))),
        StructuredStorageSettings(),
    )
    assert await reader.measure_bytes() == 17
    assert await LocalMemoryStorageUsage((vectors, vectors)).measure_bytes() == 12


async def test_unreadable_database_reports_unknown_instead_of_partial_total(tmp_path, monkeypatch):
    path = tmp_path / "protected.db"
    path.write_bytes(b"private")
    original = Path.stat

    def fail_owned_stat(self, *args, **kwargs):
        if self == path:
            raise PermissionError("unavailable")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_owned_stat)
    assert await LocalMemoryStorageUsage((path,)).measure_bytes() is None
