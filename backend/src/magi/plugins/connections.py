"""Host-owned, independently configured plugin connections.

This is a fresh registry, not an importer of package settings. Every mutation
loads the current JSON under an interprocess lock and uses optimistic revisions.
The manager owns quiescing live instances and the authority to enable them.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import shutil
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import CapabilityReadiness, ConnectionStatus, PluginConnection

from ..utils.runtime import RuntimePaths, get_runtime_paths
from .connection_persistence import connection_file_lock, write_connection_json


class ConnectionNotFoundError(KeyError):
    """The requested connection does not exist."""


class ConnectionRevisionError(ValueError):
    """A caller attempted to replace a newer connection snapshot."""

    def __init__(self, actual_revision: int) -> None:
        super().__init__("Connection changed; reload before retrying")
        self.actual_revision = actual_revision


class ConnectionStoreError(RuntimeError):
    """A registry is corrupt or uses an unsupported schema; never reset it."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: PluginConnection
    credentials: dict[str, str] = Field(default_factory=dict, repr=False)
    private_state: dict[str, JsonValue] = Field(default_factory=dict)
    content_state: dict[str, JsonValue] = Field(default_factory=dict)
    state_revision: int = Field(default=0, ge=0)
    readiness: list[CapabilityReadiness] = Field(default_factory=list)


class _Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    connections: dict[str, _Record] = Field(default_factory=dict)


def _check_revision(actual: int, expected: int) -> None:
    if isinstance(expected, bool) or expected != actual:
        raise ConnectionRevisionError(actual)


class ConnectionCredentials:
    """A host-issued credential capability bound to one connection."""

    def __init__(self, store: PluginConnectionStore, connection_id: str) -> None:
        self._store = store
        self._connection_id = connection_id

    def get(self, key: str) -> str | None:
        return self._store._credential(self._connection_id, key)

    def set(self, key: str, value: str) -> None:
        self._store._write_credential(self._connection_id, key, value)

    def delete(self, key: str) -> None:
        self._store._write_credential(self._connection_id, key, None)


class PluginConnectionStore:
    """Connection JSON and private directories under the selected runtime root.

    ``require_package`` must reject absent or library packages. ``authorize_enable``
    must check current package integrity, install consent and connection grants;
    missing authorization fails closed. These callbacks never grant permissions.
    Public I/O is synchronous for the existing plugin lifecycle executor.
    """

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths | None = None,
        require_package: Callable[[str], object],
        authorize_enable: Callable[[PluginConnection], object] | None = None,
        validate_settings: Callable[[PluginConnection], None] | None = None,
    ) -> None:
        paths = runtime_paths if runtime_paths is not None else get_runtime_paths()
        self.root = paths.runtime_dir.absolute() / "plugin-connections"
        self.path = self.root / "state.json"
        self._require_package = require_package
        self._authorize_enable = authorize_enable
        self._validate_settings = validate_settings

    def _read(self) -> _Registry:
        try:
            payload = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _Registry()
        try:
            registry = _Registry.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise ConnectionStoreError("Plugin connection registry is invalid") from exc
        for key, record in registry.connections.items():
            if key != record.connection.connection_id or re.fullmatch(r"conn_[0-9a-f]{32}", key) is None:
                raise ConnectionStoreError("Plugin connection registry identity is invalid")
            if any(ref not in record.credentials for ref in record.connection.credential_refs.values()):
                raise ConnectionStoreError("Plugin connection credential reference is invalid")
            refs = list(record.connection.credential_refs.values())
            if len(refs) != len(set(refs)):
                raise ConnectionStoreError("Plugin connection credential references are not unique")
        return registry

    def _write(self, registry: _Registry) -> None:
        payload = json.dumps(registry.model_dump(mode="python"), ensure_ascii=False, allow_nan=False, indent=2)
        write_connection_json(self.path, payload + "\n")

    @staticmethod
    def _record(registry: _Registry, connection_id: str) -> _Record:
        try:
            return registry.connections[connection_id]
        except KeyError as exc:
            raise ConnectionNotFoundError(connection_id) from exc

    def _admit(self, connection: PluginConnection) -> None:
        self._require_package(connection.plugin_id)
        if self._validate_settings is not None:
            self._validate_settings(connection)
        elif connection.settings:
            raise ValueError("A settings schema validator is required")
        if connection.enabled:
            if self._authorize_enable is None:
                raise PermissionError("Connection enable authorization is required")
            if self._authorize_enable(connection) is False:
                raise PermissionError("Connection enable authorization was denied")

    @staticmethod
    def _credentials(record: _Record, updates: dict[str, str | None]) -> None:
        refs = dict(record.connection.credential_refs)
        for key, value in updates.items():
            if not key.strip() or len(key) > 256:
                raise ValueError("Credential key must contain between 1 and 256 characters")
            old_ref = refs.pop(key, None)
            if old_ref is not None:
                record.credentials.pop(old_ref, None)
            if value is not None:
                if not isinstance(value, str) or not value:
                    raise ValueError("Credential value must be a nonempty string")
                reference = f"cred_{uuid4().hex}"
                refs[key] = reference
                record.credentials[reference] = value
        record.connection = record.connection.model_copy(update={"credential_refs": refs})

    def create(
        self,
        plugin_id: str,
        *,
        display_name: str,
        settings: dict[str, JsonValue] | None = None,
        credentials: dict[str, str] | None = None,
        enabled: bool = False,
    ) -> PluginConnection:
        """Create an explicit account/directory instance; never reuse a package ID."""
        connection = PluginConnection(
            connection_id=f"conn_{uuid4().hex}", plugin_id=plugin_id,
            display_name=display_name.strip(), settings=settings or {}, enabled=enabled,
        )
        record = _Record(connection=connection)
        self._credentials(record, credentials or {})
        with connection_file_lock(self.root):
            self._admit(record.connection)
            registry = self._read()
            registry.connections[connection.connection_id] = record
            self._write(registry)
        return record.connection.model_copy(deep=True)

    def list(self, plugin_id: str | None = None) -> list[PluginConnection]:
        """List explicit persisted connections, without synthesizing defaults."""
        with connection_file_lock(self.root):
            if plugin_id is not None:
                self._require_package(plugin_id)
            return [record.connection.model_copy(deep=True) for record in self._read().connections.values()
                    if plugin_id is None or record.connection.plugin_id == plugin_id]

    def get(self, connection_id: str) -> PluginConnection:
        with connection_file_lock(self.root):
            return self._record(self._read(), connection_id).connection.model_copy(deep=True)

    def update(
        self,
        connection_id: str,
        *,
        expected_revision: int,
        display_name: str | None = None,
        enabled: bool | None = None,
        settings: dict[str, JsonValue] | None = None,
        credentials: dict[str, str | None] | None = None,
        credential_refs: dict[str, str] | None = None,
    ) -> PluginConnection:
        """Replace supplied setting maps atomically; omitted fields remain intact."""
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            current = record.connection
            _check_revision(current.revision, expected_revision)
            values = current.model_dump()
            for key, value in (("display_name", display_name), ("enabled", enabled),
                               ("settings", settings), ("credential_refs", credential_refs)):
                if value is not None:
                    values[key] = value.strip() if key == "display_name" else value
            values["revision"] = current.revision + 1
            record.connection = PluginConnection.model_validate(values)
            if any(ref not in record.credentials for ref in record.connection.credential_refs.values()):
                raise PermissionError("Credential references must belong to this connection")
            refs = list(record.connection.credential_refs.values())
            if len(refs) != len(set(refs)):
                raise ValueError("Credential references must be unique")
            self._credentials(record, credentials or {})
            retained = set(record.connection.credential_refs.values())
            record.credentials = {key: value for key, value in record.credentials.items() if key in retained}
            self._admit(record.connection)
            record.readiness = []
            self._write(registry)
            return record.connection.model_copy(deep=True)

    def _instance_dir(self, connection_id: str) -> Path:
        return self.root / "instances" / connection_id

    def context(self, connection_id: str) -> PluginContext:
        """Allocate private host directories and a scoped credential port."""
        with connection_file_lock(self.root):
            connection = self._record(self._read(), connection_id).connection.model_copy(deep=True)
            self._require_package(connection.plugin_id)
            instance_dir = self._instance_dir(connection_id)
            instance_dir.parent.mkdir(mode=0o700, exist_ok=True)
            instance_dir.mkdir(mode=0o700, exist_ok=True)
            state_dir, resources_dir = instance_dir / "state", instance_dir / "resources"
            state_dir.mkdir(mode=0o700, exist_ok=True)
            resources_dir.mkdir(mode=0o700, exist_ok=True)
            return PluginContext(connection, state_dir, resources_dir, ConnectionCredentials(self, connection_id))

    def _credential(self, connection_id: str, key: str) -> str | None:
        with connection_file_lock(self.root):
            record = self._record(self._read(), connection_id)
            reference = record.connection.credential_refs.get(key)
            return record.credentials.get(reference) if reference is not None else None

    def _write_credential(self, connection_id: str, key: str, value: str | None) -> None:
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            self._require_package(record.connection.plugin_id)
            if value is None and key not in record.connection.credential_refs:
                return
            self._credentials(record, {key: value})
            record.connection = record.connection.model_copy(update={"revision": record.connection.revision + 1})
            record.readiness = []
            self._write(registry)

    def read_state(self, connection_id: str) -> tuple[int, dict[str, JsonValue], dict[str, JsonValue]]:
        """Return host JSON state and its independent optimistic revision."""
        with connection_file_lock(self.root):
            record = self._record(self._read(), connection_id)
            return record.state_revision, record.private_state, record.content_state

    def write_state(
        self, connection_id: str, *, expected_revision: int,
        private_state: dict[str, JsonValue], content_state: dict[str, JsonValue],
    ) -> int:
        """Keep account/progress state separate from clearable user content."""
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            _check_revision(record.state_revision, expected_revision)
            updated = _Record.model_validate({**record.model_dump(), "private_state": private_state,
                                             "content_state": content_state, "state_revision": record.state_revision + 1})
            registry.connections[connection_id] = updated
            self._write(registry)
            return updated.state_revision

    def get_readiness(self, connection_id: str) -> list[CapabilityReadiness]:
        with connection_file_lock(self.root):
            record = self._record(self._read(), connection_id)
            if not record.connection.enabled:
                if record.readiness and all(item.status != ConnectionStatus.READY for item in record.readiness):
                    return record.readiness
                return [CapabilityReadiness(capability_id="connection", connection_id=connection_id,
                                            status=ConnectionStatus.DISABLED)]
            return record.readiness or [CapabilityReadiness(
                capability_id="connection", connection_id=connection_id,
                status=ConnectionStatus.SETUP_REQUIRED, reason_code="not_checked",
            )]

    def set_readiness(
        self, connection_id: str, readiness: list[CapabilityReadiness], *, expected_revision: int,
    ) -> None:
        """Publish only a host-evaluated snapshot for the current configuration."""
        if any(item.connection_id != connection_id for item in readiness):
            raise ValueError("Readiness belongs to a different connection")
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            _check_revision(record.connection.revision, expected_revision)
            record.readiness = readiness
            self._write(registry)

    def clear_content(self, connection_id: str, *, expected_revision: int) -> PluginConnection:
        """Clear managed resources/content state after the manager has drained work.

        Retain the connection, settings, credential references, credential values,
        account state and source cursors. Host memory and plugin clear hooks are
        separate lifecycle participants and must complete before API success.
        """
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            _check_revision(record.connection.revision, expected_revision)
            resources = self._instance_dir(connection_id) / "resources"
            if resources.exists():
                shutil.rmtree(resources)
                resources.mkdir(mode=0o700)
            record.content_state = {}
            record.state_revision += 1
            record.connection = record.connection.model_copy(update={"revision": record.connection.revision + 1})
            self._write(registry)
            return record.connection.model_copy(deep=True)

    def disconnect(self, connection_id: str, *, expected_revision: int) -> None:
        """Erase this instance and credentials after revocation and runtime shutdown.

        Installed packages and previously ingested host memory remain. No source
        directory or remote provider content is ever deleted.
        """
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            _check_revision(record.connection.revision, expected_revision)
            instance_dir = self._instance_dir(connection_id)
            if instance_dir.exists():
                shutil.rmtree(instance_dir)
            del registry.connections[connection_id]
            self._write(registry)
