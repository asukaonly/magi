"""Early storage plugin composition without queues, tools or domain consumers."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml
import json
from magi_plugin_sdk.fs import read_managed_bytes
from magi_plugin_sdk.storage import StorageDomain

from ..config.plugin_models import PluginSettings
from ..config.storage_models import StructuredStorageSettings
from ..plugins.discovery import default_builtin_root
from ..plugins.storage_runtime import StoragePluginRuntime
from ..utils.packaged_paths import get_repo_root
from ..utils.runtime import RuntimePaths
from .context import RuntimeBootstrapContext, require_initialized
from .lifecycle import LifecycleModule
from .sqlite_storage_provider import SqliteStorageProvider


def read_mapping(path: Path) -> dict[str, Any]:
    if not path.parent.exists():
        return {}
    payload = read_managed_bytes(path, max_bytes=4 * 1024 * 1024)
    value = yaml.safe_load(payload) if payload else {}
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Storage bootstrap configuration must be a mapping")
    return value


def read_storage_settings(paths: RuntimePaths) -> StructuredStorageSettings:
    return StructuredStorageSettings.model_validate(read_mapping(paths.config_dir / "agent.yaml").get("structured_storage", {}))


def build_storage_plugin_runtime(paths: RuntimePaths) -> StoragePluginRuntime:
    agent = read_mapping(paths.config_dir / "agent.yaml")
    metadata = read_mapping(paths.config_dir / "plugins" / "index.yaml")
    packages = {key: PluginSettings.model_validate(value) for key, value in metadata.get("packages", {}).items()}
    search_paths = [default_builtin_root(), paths.base_dir / "plugins"]
    for value in agent.get("plugins", {}).get("scan_paths", []):
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = get_repo_root() / path
        if path not in search_paths:
            search_paths.append(path)

    def bind_builtin(manifest: Any, instance: Any) -> None:
        if manifest.plugin_id != "storage-sqlite":
            raise ValueError("Unknown bundled storage provider")
        instance.bind_provider(SqliteStorageProvider(paths))

    def guard_mutation(plugin_id: str, connection_id: str | None) -> None:
        from .storage_selection import BINDING_PATHS
        references = []
        for relative in BINDING_PATHS.values():
            path = paths.data_dir / relative
            if not path.parent.exists():
                continue
            payload = read_managed_bytes(path, max_bytes=16384)
            if payload is None:
                continue
            value = json.loads(payload)
            references.extend(target for target in (
                value.get("active"), (value.get("pending") or {}).get("destination"),
            ) if target is not None)
        for target in references:
            if target.get("plugin_id") == plugin_id and (connection_id is None or target.get("connection_id") == connection_id):
                raise ValueError("Bound storage requires offline maintenance before replacement")
        settings = read_storage_settings(paths)
        for domain in ("chat", "channels", "memory_events"):
            selection = getattr(settings, domain)
            if selection.connection_id is None:
                if plugin_id == "storage-sqlite":
                    raise ValueError("Default SQLite storage requires offline maintenance before replacement")
            elif connection_id is None or selection.connection_id == connection_id:
                connection = runtime.connections.get(selection.connection_id)
                if connection.plugin_id == plugin_id:
                    raise ValueError("Selected storage requires offline maintenance before replacement")

    runtime = StoragePluginRuntime(paths=paths, search_paths=search_paths, packages=packages,
                                   bind_builtin=bind_builtin, guard_mutation=guard_mutation)
    return runtime


class StoragePluginBootstrapModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(name="runtime_storage_plugins", dependencies=("runtime_initialization_state",))
        self.context = context

    async def init(self) -> None:
        paths = require_initialized(self.context.core.runtime_paths, "runtime paths")
        self.context.plugins.storage_runtime = build_storage_plugin_runtime(paths)

    async def shutdown(self) -> None:
        runtime = self.context.plugins.storage_runtime
        self.context.plugins.storage_runtime = None
        if runtime is not None:
            await runtime.close()
