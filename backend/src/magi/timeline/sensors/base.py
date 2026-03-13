"""Base contracts for timeline sensors."""
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

from ...plugins.i18n import PluginI18n, get_current_language
from ..contracts import TimelineContentBlock, TimelineEvent
from ..sync import SensorSyncContext, SensorSyncResult


class TimelineSensorBase(ABC):
    """Shared contract for timeline source sensors."""

    sensor_id: str = "timeline.base"
    display_name: str = "Timeline Source"
    source_type: str = "unknown"
    polling_mode: str = "interval"
    default_interval: int = 15
    supports_retention_modes: tuple[str, ...] = ("retain_raw", "analyze_only")
    supports_content_blocks: tuple[str, ...] = ("text",)
    update_key_fields: tuple[str, ...] = ()
    config_schema: dict[str, Any] = {}
    relation_edge_whitelist: tuple[str, ...] = ()
    capabilities: dict[str, Any] = {}
    supports_pull_sync: bool = False
    supports_watch_mode: bool = False

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        source_path: Optional[str] = None,
        fetch_page_content: bool = False,
    ) -> None:
        self.retention_mode = retention_mode or self.default_retention_mode
        self.source_path = source_path
        self.fetch_page_content = fetch_page_content
        self._plugin_id: str | None = None
        self._plugin_dir: Path | None = None
        self._i18n: PluginI18n | None = None

    @property
    def default_retention_mode(self) -> str:
        return "analyze_only"

    def bind_plugin_context(self, *, plugin_id: str | None = None, plugin_dir: str | Path | None = None) -> None:
        """Bind plugin metadata needed for sensor-local translations."""
        self._plugin_id = plugin_id or self._plugin_id
        self._plugin_dir = Path(plugin_dir) if plugin_dir is not None else self._plugin_dir
        self._i18n = None

    @property
    def plugin_id(self) -> str:
        """Best-effort plugin identifier used for translation lookup."""
        if self._plugin_id:
            return self._plugin_id
        manifest_path = self._manifest_path()
        if manifest_path is not None and manifest_path.exists():
            try:
                with manifest_path.open("rb") as handle:
                    raw = tomllib.load(handle)
                plugin_block = raw.get("plugin", raw)
                plugin_id = plugin_block.get("id")
                if isinstance(plugin_id, str) and plugin_id:
                    self._plugin_id = plugin_id
                    return plugin_id
            except Exception:
                pass
        plugin_dir = self.plugin_dir
        if plugin_dir is not None:
            return plugin_dir.name
        return self.__class__.__name__

    @property
    def plugin_dir(self) -> Path | None:
        """Best-effort plugin directory used for translation lookup."""
        if self._plugin_dir is not None:
            return self._plugin_dir
        module = inspect.getmodule(self.__class__)
        if module and module.__file__:
            self._plugin_dir = Path(module.__file__).resolve().parent
        return self._plugin_dir

    @property
    def i18n(self) -> PluginI18n:
        """Get the i18n helper for this sensor's plugin."""
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
        """Translate sensor-local content using the owning plugin's dictionaries."""
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
        plugin_id = self.plugin_id
        candidates = {
            plugin_id,
            plugin_id.replace("-", "_"),
            plugin_id.replace("_", "-"),
            plugin_dir.name,
        }
        for candidate in candidates:
            if not candidate:
                continue
            candidate_dir = parent / candidate
            if (candidate_dir / "i18n").exists():
                return candidate_dir
        return plugin_dir

    def source_item_identity(self, item: dict[str, Any]) -> str:
        identity_parts = [str(item.get(field, "")) for field in self.update_key_fields]
        return ":".join(identity_parts)

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        version_parts = [str(item.get(field, "")) for field in self.update_key_fields]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def discover_changes(
        self,
        items: list[dict[str, Any]],
        known_fingerprints: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        known = known_fingerprints or set()
        return [item for item in items if self.source_item_version_fingerprint(item) not in known]

    async def fetch_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return dict(item)

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        _ = context
        raise NotImplementedError(f"{self.sensor_id} does not implement pull sync")

    @abstractmethod
    async def build_timeline_event(self, item: dict[str, Any]) -> TimelineEvent:
        """Convert a source item into a normalized timeline event."""

    async def resolve_retention_assets(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        _ = item
        return []

    async def extract_candidates(self, item: dict[str, Any]) -> dict[str, Any]:
        _ = item
        return {"entities": [], "tags": [], "relation_candidates": []}

    def _build_event(
        self,
        *,
        source_item_id: str,
        title: str,
        summary: str,
        occurred_at: Optional[float] = None,
        raw_payload_ref: Optional[str] = None,
        content_blocks: Optional[list[TimelineContentBlock]] = None,
        tags: Optional[list[str]] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> TimelineEvent:
        now = time.time()
        event_id = f"{self.source_type}:{source_item_id}"
        return TimelineEvent(
            event_id=event_id,
            source_type=self.source_type,
            source_item_id=source_item_id,
            occurred_at=float(occurred_at or now),
            captured_at=now,
            title=title,
            summary=summary,
            retention_mode=self.retention_mode,
            raw_payload_ref=raw_payload_ref,
            content_blocks=list(content_blocks or []),
            tags=list(tags or []),
            processing_status={"stored": False, "analyzed": False},
            provenance=provenance or {"sensor_id": self.sensor_id},
        )
