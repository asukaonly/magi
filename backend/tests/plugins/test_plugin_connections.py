"""Durability, isolation and authority tests for plugin connections."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from magi_plugin_sdk.runtime import CapabilityReadiness, ConnectionStatus

from magi.plugins.connections import (
    ConnectionNotFoundError, ConnectionRevisionError, ConnectionStoreError, PluginConnectionStore,
)
from magi.utils.runtime import RuntimePaths


def _require_package(plugin_id: str) -> None:
    if plugin_id != "example":
        raise KeyError("Plugin package not found")


@pytest.fixture
def store(tmp_path):
    return PluginConnectionStore(runtime_paths=RuntimePaths(tmp_path / "runtime-home"), require_package=_require_package,
                                 validate_settings=lambda connection: None)


def test_multiple_connections_persist_without_package_defaults(store):
    assert store.list("example") == []
    first = store.create("example", display_name="Work", settings={"source": {"directory": "/work"}})
    second = store.create("example", display_name="Home", settings={"source": {"directory": "/home"}})
    assert first.connection_id != second.connection_id
    reopened = PluginConnectionStore(runtime_paths=RuntimePaths(store.root.parents[1]), require_package=_require_package)
    assert reopened.list("example") == [first, second]
    assert reopened.path == store.path
    assert "plugins/packages" not in str(store.path)


def test_absent_package_and_unapproved_enable_never_write(store):
    with pytest.raises(KeyError):
        store.create("absent", display_name="Missing")
    with pytest.raises(PermissionError):
        store.create("example", display_name="Unapproved", enabled=True)
    connection = store.create("example", display_name="Work")
    with pytest.raises(PermissionError):
        store.update(connection.connection_id, expected_revision=0, enabled=True)
    assert store.get(connection.connection_id) == connection


def test_optimistic_revision_is_atomic_across_threads_and_store_instances(store):
    connection = store.create("example", display_name="Original")

    def update(name):
        other = PluginConnectionStore(runtime_paths=RuntimePaths(store.root.parents[1]), require_package=_require_package)
        try:
            return other.update(connection.connection_id, expected_revision=0, display_name=name)
        except ConnectionRevisionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["First", "Second"]))
    assert sum(result is not None for result in results) == 1
    assert store.get(connection.connection_id).revision == 1


def test_optimistic_revision_survives_cross_process_races(store):
    connection = store.create("example", display_name="Original")
    script = """
import sys
from pathlib import Path
from magi.plugins.connections import PluginConnectionStore, ConnectionRevisionError
from magi.utils.runtime import RuntimePaths
s = PluginConnectionStore(runtime_paths=RuntimePaths(Path(sys.argv[1])), require_package=lambda p: None)
try:
    s.update(sys.argv[2], expected_revision=0, display_name=sys.argv[3])
except ConnectionRevisionError:
    sys.exit(7)
"""
    processes = [subprocess.Popen([sys.executable, "-c", script, str(store.root.parents[1]), connection.connection_id, name],
                                  env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for name in ("First", "Second")]
    output = [process.communicate(timeout=30) for process in processes]
    assert sorted(process.returncode for process in processes) == [0, 7], output


def test_credentials_are_scoped_write_only_and_cannot_be_rebound(store):
    first = store.create("example", display_name="Work", credentials={"token": "work-secret"})
    second = store.create("example", display_name="Home", credentials={"token": "home-secret"})
    first_port = store.context(first.connection_id).credentials
    second_port = store.context(second.connection_id).credentials
    assert first_port.get("token") == "work-secret"
    assert second_port.get("token") == "home-secret"
    assert "work-secret" not in first.model_dump_json()
    with pytest.raises(PermissionError):
        store.update(second.connection_id, expected_revision=0, credential_refs=first.credential_refs)
    first_port.set("token", "updated-secret")
    assert first_port.get("token") == "updated-secret"
    assert second_port.get("token") == "home-secret"
    assert store.get(first.connection_id).revision == 1
    first_port.delete("token")
    assert first_port.get("token") is None
    assert store.get(first.connection_id).credential_refs == {}


def test_credential_port_updates_exact_dotted_reference_and_revokes_old_value(store):
    connection = store.create("example", display_name="Work")
    port = store.context(connection.connection_id).credentials
    key = "sources.github_activity.access_token"
    port.set(key, "first-secret")
    first = store.get(connection.connection_id)
    assert key in first.credential_refs
    assert first.revision == 1
    port.set(key, "second-secret")
    second = store.get(connection.connection_id)
    assert first.credential_refs[key] != second.credential_refs[key]
    assert "first-secret" not in store.path.read_text()
    assert port.get(key) == "second-secret"
    port.delete(key)
    after_delete = store.get(connection.connection_id)
    port.delete(key)
    assert store.get(connection.connection_id) == after_delete


def test_nonfinite_private_state_is_rejected_without_changing_persistence(store):
    connection = store.create("example", display_name="Work")
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.write_state(connection.connection_id, expected_revision=0, private_state={"value": float("inf")}, content_state={})
    assert store.path.read_bytes() == before


def test_clear_and_disconnect_have_distinct_scope(store):
    connection = store.create("example", display_name="Work", settings={"directory": "/source"}, credentials={"token": "secret"})
    context = store.context(connection.connection_id)
    (context.state_dir / "cursor.json").write_text('{"cursor": "next"}')
    (context.resources_dir / "content.txt").write_text("collected content")
    store.write_state(connection.connection_id, expected_revision=0,
                      private_state={"cursor": "next"}, content_state={"body": "content"})
    updated = store.clear_content(connection.connection_id, expected_revision=0)
    assert (context.state_dir / "cursor.json").exists()
    assert list(context.resources_dir.iterdir()) == []
    assert store.read_state(connection.connection_id) == (2, {"cursor": "next"}, {})
    assert context.credentials.get("token") == "secret"
    assert updated.settings == connection.settings
    assert updated.credential_refs == connection.credential_refs
    store.disconnect(connection.connection_id, expected_revision=updated.revision)
    assert not context.state_dir.parent.exists()
    with pytest.raises(ConnectionNotFoundError):
        context.credentials.get("token")
    assert store.list("example") == []


def test_private_state_uses_independent_revision(store):
    connection = store.create("example", display_name="Work")
    store.write_state(connection.connection_id, expected_revision=0, private_state={"cursor": 1}, content_state={})
    assert store.get(connection.connection_id).revision == 0
    with pytest.raises(ConnectionRevisionError):
        store.write_state(connection.connection_id, expected_revision=0, private_state={"cursor": 2}, content_state={})


def test_readiness_is_host_owned_and_invalidated_on_configuration_change(store):
    store._authorize_enable = lambda connection: None
    connection = store.create("example", display_name="Work", enabled=True)
    readiness = CapabilityReadiness(capability_id="source", connection_id=connection.connection_id, status=ConnectionStatus.READY)
    store.set_readiness(connection.connection_id, [readiness], expected_revision=0)
    assert store.get_readiness(connection.connection_id) == [readiness]
    updated = store.update(connection.connection_id, expected_revision=0, settings={"folder": "/new"})
    assert store.get_readiness(connection.connection_id)[0].reason_code == "not_checked"
    with pytest.raises(ConnectionRevisionError):
        store.set_readiness(connection.connection_id, [readiness], expected_revision=0)
    store.update(connection.connection_id, expected_revision=updated.revision, enabled=False)
    assert store.get_readiness(connection.connection_id)[0].status == ConnectionStatus.DISABLED


def test_invalid_schema_is_never_reset_or_migrated(store):
    store.create("example", display_name="Work")
    store.path.write_text('{"schema_version": 0, "connections": {}}')
    with pytest.raises(ConnectionStoreError):
        store.list()
    assert json.loads(store.path.read_text())["schema_version"] == 0


def test_failed_atomic_replace_preserves_previous_state(store, monkeypatch):
    connection = store.create("example", display_name="Work")
    before = store.path.read_bytes()
    def fail(*args):
        raise OSError("Disk write failed")
    monkeypatch.setattr("magi.utils.file_io.os.replace", fail)
    with pytest.raises(OSError):
        store.update(connection.connection_id, expected_revision=0, display_name="Lost")
    assert store.path.read_bytes() == before
    assert not list(store.root.glob("*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="Unix filesystem mode contract")
def test_private_paths_permissions_and_link_rejection(store, tmp_path):
    connection = store.create("example", display_name="Work")
    context = store.context(connection.connection_id)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert context.state_dir.stat().st_mode & 0o777 == 0o700
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    (context.resources_dir / "unsafe").symlink_to(outside)
    with pytest.raises(RuntimeError):
        store.clear_content(connection.connection_id, expected_revision=0)
    assert outside.read_text() == "untouched"
