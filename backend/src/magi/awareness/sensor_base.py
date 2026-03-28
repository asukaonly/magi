"""Base contract for all data collection sensors (L9 - Awareness layer)."""

from __future__ import annotations

import hashlib
import inspect
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..plugins.i18n import PluginI18n, get_current_language
from .sensor_output import ContentBlock, SensorMemoryPolicy, SensorOutput, SensorOutputMetadata
from .sensor_sync import SensorSyncContext, SensorSyncResult


class SensorBase(ABC):
    """Base contract for all data collection sensors.

    Sensors produce domain-neutral ``SensorOutput`` and declare a
    ``SensorMemoryPolicy`` that controls memory routing without depending
    on memory-layer internals.
    """

    sensor_id: str = "sensor.base"
    display_name: str = "Sensor"
    source_type: str = "unknown"
    memory_event_type: str = "SENSOR_EVENT"

    # Sync capabilities
    supports_pull_sync: bool = False
    supports_watch_mode: bool = False
    polling_mode: str = "interval"
    default_interval: int = 15

    # Dedup
    update_key_fields: tuple[str, ...] = ()

    # Memory policy
    memory_policy: SensorMemoryPolicy = SensorMemoryPolicy()

    # Knowledge graph
    relation_edge_whitelist: tuple[str, ...] = ()

    # Plugin context
    config_schema: dict[str, Any] = {}
    capabilities: dict[str, Any] = {}

    def __init__(self) -> None:
        self._plugin_id: str | None = None
        self._plugin_dir: Path | None = None
        self._i18n: PluginI18n | None = None

    # ------------------------------------------------------------------
    # Plugin context (inherited from current TimelineSensorBase)
    # ------------------------------------------------------------------

    def bind_plugin_context(
        self, *, plugin_id: str | None = None, plugin_dir: str | Path | None = None
    ) -> None:
        """Bind plugin metadata needed for sensor-local translations."""
        self._plugin_id = plugin_id or self._plugin_id
        self._plugin_dir = Path(plugin_dir) if plugin_dir is not None else self._plugin_dir
        self._i18n = None

    @property
    def plugin_id(self) -> str:
        if self._plugin_id:
            return self._plugin_id
        manifest_path = self._manifest_path()
        if manifest_path is not None and manifest_path.exists():
            try:
                with manifest_path.open("rb") as handle:
                    raw = tomllib.load(handle)
                plugin_block = raw.get("plugin", raw)
                pid = plugin_block.get("id")
                if isinstance(pid, str) and pid:
                    self._plugin_id = pid
                    return pid
            except Exception:
                pass
        plugin_dir = self.plugin_dir
        if plugin_dir is not None:
            return plugin_dir.name
        return self.__class__.__name__

    @property
    def plugin_dir(self) -> Path | None:
        if self._plugin_dir is not None:
            return self._plugin_dir
        module = inspect.getmodule(self.__class__)
        if module and module.__file__:
            self._plugin_dir = Path(module.__file__).resolve().parent
        return self._plugin_dir

    @property
    def i18n(self) -> PluginI18n:
        if self._i18n is None:
            plugin_dir = self._resolve_i18n_plugin_dir()
            if plugin_dir is None:
                self._i18n = PluginI18n(self.plugin_id, Path("."))
            else:
                self._i18n = PluginI18n(self.plugin_id, plugin_dir)
        return self._i18n

    def t(
        self,
        key: str,
        language: Optional[str] = None,
        fallback: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        effective_language = language or get_current_language()
        return self.i18n.t(key, language=effective_language, fallback=fallback, **kwargs)

    def _manifest_path(self) -> Path | None:
        plugin_dir = self.plugin_dir
        if plugin_dir is None:
            return None
        manifest_path = plugin_dir / "plugin.toml"
        return manifest_path if manifest_path.exists() else None

    def _resolve_i18n_plugin_dir(self) -> Path | None:
        plugin_dir = self.plugin_dir
        if plugin_dir is None:
            return None
        if (plugin_dir / "i18n").exists():
            return plugin_dir
        parent = plugin_dir.parent
        pid = self.plugin_id
        candidates = {
            pid,
            pid.replace("-", "_"),
            pid.replace("_", "-"),
            plugin_dir.name,
        }
        for candidate in candidates:
            if not candidate:
                continue
            candidate_dir = parent / candidate
            if (candidate_dir / "i18n").exists():
                return candidate_dir
        return plugin_dir

    # ------------------------------------------------------------------
    # Dedup helpers
    # ------------------------------------------------------------------

    def source_item_identity(self, item: dict[str, Any]) -> str:
        identity_parts = [str(item.get(f, "")) for f in self.update_key_fields]
        return ":".join(identity_parts)

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        version_parts = [str(item.get(f, "")) for f in self.update_key_fields]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def discover_changes(
        self,
        items: list[dict[str, Any]],
        known_fingerprints: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        known = known_fingerprints or set()
        return [item for item in items if self.source_item_version_fingerprint(item) not in known]

    # ------------------------------------------------------------------
    # Core sensor contract
    # ------------------------------------------------------------------

    @abstractmethod
    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        """Convert a source item into a domain-neutral sensor output."""

    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        """Extract entities, tags, and relation candidates from a source item."""
        return SensorOutputMetadata()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Pull-sync: collect source items. Override in pull-sync capable sensors."""
        _ = context
        raise NotImplementedError(f"{self.sensor_id} does not implement pull sync")

    async def fetch_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Optional pre-processing/enrichment before build_output."""
        return dict(item)

    def l2_batch_owner(self, output: SensorOutput) -> str | None:
        """Return an optional stable L2 microbatch owner key for sensor events."""
        _ = output
        return None

    def idempotency_key(self, output: SensorOutput) -> str | None:
        """Return an optional business-level idempotency key for sensor events."""
        value = str(output.source_item_id or "").strip()
        return value or None

    # ------------------------------------------------------------------
    # Convenience builder
    # ------------------------------------------------------------------

    def _build_output(
        self,
        *,
        source_item_id: str,
        title: str,
        summary: str,
        occurred_at: float | None = None,
        raw_payload_ref: str | None = None,
        content_blocks: list[ContentBlock] | None = None,
        tags: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        domain_payload: dict[str, Any] | None = None,
    ) -> SensorOutput:
        """Convenience builder analogous to TimelineSensorBase._build_event."""
        now = time.time()
        return SensorOutput(
            source_type=self.source_type,
            source_item_id=source_item_id,
            occurred_at=float(occurred_at or now),
            captured_at=now,
            title=title,
            summary=summary,
            raw_payload_ref=raw_payload_ref,
            content_blocks=list(content_blocks or []),
            tags=list(tags or []),
            provenance=provenance or {"sensor_id": self.sensor_id},
            domain_payload=domain_payload or {},
        )
