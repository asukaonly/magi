"""Host-owned, independently configured plugin connections.

This is a fresh registry, not an importer of package settings. Every mutation
loads the current JSON under an interprocess lock and uses optimistic revisions.
The manager owns quiescing live instances and the authority to enable them.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.runtime import CapabilityReadiness, ConnectionStatus, PluginConnection

from ..core.secret_store import (
    SecretStore,
    get_secret_store,
    is_secret_ref,
    make_secret_ref,
)
from ..utils.runtime import RuntimePaths, get_runtime_paths
from .connection_persistence import connection_file_lock, write_connection_json

logger = logging.getLogger(__name__)


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


class _IngressEpoch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    epoch: UUID


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
        secret_store: SecretStore | None = None,
    ) -> None:
        paths = runtime_paths if runtime_paths is not None else get_runtime_paths()
        self.root = paths.runtime_dir.absolute() / "plugin-connections"
        self.path = self.root / "state.json"
        self._require_package = require_package
        self._authorize_enable = authorize_enable
        self._validate_settings = validate_settings
        self._secret_store_override = secret_store

    def _secret_store(self) -> SecretStore:
        return self._secret_store_override if self._secret_store_override is not None else get_secret_store()

    @staticmethod
    def _rollback_secrets(
        store: SecretStore,
        entries: list[tuple[str, str | None]],
    ) -> None:
        for secret_ref, previous in reversed(entries):
            try:
                if previous is None:
                    store.delete(secret_ref)
                else:
                    store.set(secret_ref, previous)
            except Exception:
                pass

    @staticmethod
    def _delete_stale_secrets(store: SecretStore, refs: list[str]) -> None:
        for secret_ref in refs:
            if not is_secret_ref(secret_ref):
                continue
            try:
                store.delete(secret_ref)
            except Exception:
                logger.debug("Ignoring stale plugin secret deletion failure for %s", secret_ref)

    def _migrate_plaintext_credentials(self, registry: _Registry) -> None:
        """Atomically migrate legacy plaintext plugin credentials in state.json into SecretStore."""
        pending: list[tuple[_Record, str, str, str]] = []
        for connection_id, record in registry.connections.items():
            for ref, stored in record.credentials.items():
                if stored and not is_secret_ref(stored):
                    secret_ref = make_secret_ref("plugins", connection_id, ref)
                    pending.append((record, ref, secret_ref, stored))
        if not pending:
            return
        store = self._secret_store()
        rollback: list[tuple[str, str | None]] = []
        original_values: list[tuple[_Record, str, str]] = []
        try:
            for record, ref, secret_ref, plaintext in pending:
                prev = store.get(secret_ref)
                store.set(secret_ref, plaintext)
                rollback.append((secret_ref, prev))
                original_values.append((record, ref, plaintext))
                record.credentials[ref] = secret_ref
            self._write(registry)
            logger.info(
                "Migrated legacy plaintext plugin credentials to secret store | count=%d",
                len(pending),
            )
        except Exception as exc:
            for record, ref, plaintext in original_values:
                record.credentials[ref] = plaintext
            self._rollback_secrets(store, rollback)
            logger.warning(
                "Failed to migrate plaintext plugin credentials; preserving existing state.json | error=%s",
                str(exc),
            )

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
        self._migrate_plaintext_credentials(registry)
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

    def _credentials(
        self,
        record: _Record,
        updates: dict[str, str | None],
    ) -> tuple[list[tuple[str, str | None]], list[str]]:
        for key, value in updates.items():
            if not key.strip() or len(key) > 256:
                raise ValueError("Credential key must contain between 1 and 256 characters")
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("Credential value must be a nonempty string")

        store = self._secret_store()
        refs = dict(record.connection.credential_refs)
        rollback: list[tuple[str, str | None]] = []
        stale_refs: list[str] = []
        try:
            for key, value in updates.items():
                old_ref = refs.pop(key, None)
                if old_ref is not None:
                    old_stored = record.credentials.pop(old_ref, None)
                    if is_secret_ref(old_stored):
                        stale_refs.append(str(old_stored))
                if value is not None:
                    reference = f"cred_{uuid4().hex}"
                    secret_ref = make_secret_ref(
                        "plugins",
                        record.connection.connection_id,
                        reference,
                    )
                    prev = store.get(secret_ref)
                    store.set(secret_ref, value)
                    rollback.append((secret_ref, prev))
                    refs[key] = reference
                    record.credentials[reference] = secret_ref
        except Exception:
            self._rollback_secrets(store, rollback)
            raise
        record.connection = record.connection.model_copy(update={"credential_refs": refs})
        return rollback, stale_refs

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
        rollback: list[tuple[str, str | None]] = []
        stale_refs: list[str] = []
        try:
            rollback, stale_refs = self._credentials(record, credentials or {})
            with connection_file_lock(self.root):
                self._admit(record.connection)
                registry = self._read()
                registry.connections[connection.connection_id] = record
                self._write(registry)
        except Exception:
            self._rollback_secrets(self._secret_store(), rollback)
            raise
        self._delete_stale_secrets(self._secret_store(), stale_refs)
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

    def ingress_epoch(self, connection_id: str) -> str:
        """Return the host-owned generation used to fence delayed observations."""
        with connection_file_lock(self.root):
            self._record(self._read(), connection_id)
            path = self.root / f"{connection_id}.ingress.json"
            if not path.exists():
                # A connection's first generation is its immutable host-issued identity.
                return str(UUID(connection_id.removeprefix("conn_")))
            try:
                return str(_IngressEpoch.model_validate_json(path.read_text()).epoch)
            except (OSError, ValueError) as exc:
                raise ConnectionStoreError("Plugin ingress epoch is invalid") from exc

    def collector_binding(self, connection_id: str, source_type: str) -> str | None:
        """Read collection ownership independently of plugin credentials and settings."""
        with connection_file_lock(self.root):
            self._record(self._read(), connection_id)
            path = self.root / f"{connection_id}.collectors.json"
            if not path.exists():
                return None
            bindings = json.loads(path.read_text())
            if not isinstance(bindings, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items()):
                raise ConnectionStoreError("Collector bindings are invalid")
            return bindings.get(source_type)

    def bind_collector(self, connection_id: str, source_type: str, client_id: str | None) -> None:
        """Called only by the host after authenticated source admission is drained."""
        with connection_file_lock(self.root):
            self._record(self._read(), connection_id)
            path = self.root / f"{connection_id}.collectors.json"
            bindings = json.loads(path.read_text()) if path.exists() else {}
            if client_id is None:
                bindings.pop(source_type, None)
            else:
                bindings[source_type] = client_id
            write_connection_json(path, json.dumps(bindings))

    def invalidate_ingress(self, connection_id: str, *, expected_revision: int) -> None:
        """Fence old observations durably before any content is erased."""
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            _check_revision(record.connection.revision, expected_revision)
            write_connection_json(self.root / f"{connection_id}.ingress.json",
                                  _IngressEpoch(epoch=uuid4()).model_dump_json())

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
            rollback: list[tuple[str, str | None]] = []
            stale_refs: list[str] = []
            try:
                rollback, stale_refs = self._credentials(record, credentials or {})
                retained = set(record.connection.credential_refs.values())
                for ref, stored in list(record.credentials.items()):
                    if ref not in retained and is_secret_ref(stored):
                        stale_refs.append(str(stored))
                record.credentials = {key: value for key, value in record.credentials.items() if key in retained}
                self._admit(record.connection)
                record.readiness = []
                self._write(registry)
            except Exception:
                self._rollback_secrets(self._secret_store(), rollback)
                raise
            self._delete_stale_secrets(self._secret_store(), stale_refs)
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
            if reference is None:
                return None
            stored = record.credentials.get(reference)
            if stored is None:
                return None
            if is_secret_ref(stored):
                return self._secret_store().get(stored)
            return stored

    def _write_credential(self, connection_id: str, key: str, value: str | None) -> None:
        with connection_file_lock(self.root):
            registry = self._read()
            record = self._record(registry, connection_id)
            self._require_package(record.connection.plugin_id)
            if value is None and key not in record.connection.credential_refs:
                return
            rollback: list[tuple[str, str | None]] = []
            stale_refs: list[str] = []
            try:
                rollback, stale_refs = self._credentials(record, {key: value})
                record.connection = record.connection.model_copy(update={"revision": record.connection.revision + 1})
                record.readiness = []
                self._write(registry)
            except Exception:
                self._rollback_secrets(self._secret_store(), rollback)
                raise
            self._delete_stale_secrets(self._secret_store(), stale_refs)

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
            secret_refs_to_delete = [
                str(val) for val in record.credentials.values() if is_secret_ref(val)
            ]
            del registry.connections[connection_id]
            self._write(registry)
            self._delete_stale_secrets(self._secret_store(), secret_refs_to_delete)
            (self.root / f"{connection_id}.ingress.json").unlink(missing_ok=True)
            (self.root / f"{connection_id}.collectors.json").unlink(missing_ok=True)
