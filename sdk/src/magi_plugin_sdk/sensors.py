"""Sensor authoring contracts for Magi plugins."""
from __future__ import annotations

import hashlib
import inspect
import json
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .contracts import ExtensionFieldSpec
from .i18n import PluginI18n, get_current_language
from .user_content import UserContentClearContext
from .runtime import PluginConnection, SourceChange, SourceChangeBatch

if TYPE_CHECKING:
    from .context import PluginContext


@dataclass(slots=True)
class SensorSpec:
    """Declarative metadata for a sensor contribution."""

    sensor_id: str
    display_name: str
    description: str = ""
    domain: str = "general"
    surface: str = "extensions"
    sync_mode: str = "manual"
    polling_mode: str = "manual"
    fields: list[ExtensionFieldSpec] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ContentBlock:
    """A typed content fragment within a sensor output."""

    kind: str
    value: str
    mime_type: str | None = None


@dataclass(slots=True, frozen=True)
class ActivityFacet:
    """One stable semantic facet used to describe a sensor event."""

    code: str
    i18n_key: str
    fallback: str = ""
    embedding_fallback: str | None = None


@dataclass(slots=True, frozen=True)
class SensorActivity:
    """Structured source/action semantics emitted by a sensor event."""

    source: ActivityFacet
    action: ActivityFacet
    object: ActivityFacet | None = None
    # Qualifiers carry typed scalar values — str/int/float/bool. Plugins
    # were previously coerced to str across the board, which round-tripped
    # ints like capture_count and duration_seconds through JSON as strings
    # ("1", "0") and made downstream aggregation awkward. Keep the native
    # type when it's a JSON-safe primitive; coerce anything else to str.
    qualifiers: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SensorNarration:
    """Human-authored factual narration emitted by a sensor event."""

    body: str = ""
    title: str | None = None


@dataclass(slots=True, frozen=True)
class TimelinePresentation:
    """Hint for how a sensor event should appear in the main timeline."""

    mode: str = "full"
    title: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        normalized_mode = str(self.mode or "full").strip() or "full"
        if normalized_mode not in {"full", "compact", "evidence_only"}:
            raise ValueError(
                "TimelinePresentation.mode must be one of: full, compact, evidence_only"
            )
        object.__setattr__(self, "mode", normalized_mode)
        object.__setattr__(self, "title", _clean_optional_text(self.title))
        object.__setattr__(self, "summary", _clean_optional_text(self.summary))


@dataclass(slots=True, frozen=True)
class SensorMemoryPolicy:
    """Declarative memory routing policy for a sensor's outputs."""

    memory_domain: str = "external_activity"
    ingest_target: str = "l1_only"
    cognition_eligible: bool = True
    tom_depth: str = "none"
    retention_class: str = "compressible"
    importance_bias: float = 0.5
    author_type: str = "external"
    content_type: str = "observation"
    # When False, L2 does deterministic direct-writes (entities + structured graph hints)
    # but skips the LLM phase1/2 extraction — for high-volume / low-signal or purely
    # structured sources where the LLM adds little (e.g. git sessions).
    allow_llm_extraction: bool = True
    # > 0 enables the P2 frequency gate: an event runs structured-only until its per-event
    # promotion_key (emitted in metadata) has been seen this many times, then full extraction.
    promotion_threshold: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SensorMemoryPolicy":
        return cls(**data)


@dataclass(slots=True)
class SensorOutput:
    """Domain-neutral output produced by all sensors."""

    source_type: str
    source_item_id: str
    occurred_at: float
    captured_at: float
    activity: SensorActivity
    narration: SensorNarration
    content_blocks: list[ContentBlock] = field(default_factory=list)
    raw_payload_ref: str | None = None
    # Capture-time full text pinned for L2 (RFC #56 P3): obsidian note body, git
    # commit text, etc. ``narration.body`` / ``content`` stay a lean summary;
    # this frozen snapshot is stored in the L1 pinned-payload satellite and read
    # by L2 at extraction time (never re-fetched from the live source).
    pinned_payload: str | None = None
    # Per-event promotion escape hatch (RFC #56 P4): "force_full" runs full L2
    # extraction and "force_structured_only" skips it, either way overriding the
    # generic policy (P1 static flag) and frequency gate (P2). None -> default.
    promotion_override: str | None = None
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    domain_payload: dict[str, Any] = field(default_factory=dict)
    timeline_presentation: TimelinePresentation = field(default_factory=TimelinePresentation)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["content_blocks"] = [asdict(block) for block in self.content_blocks]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorOutput:
        blocks = [
            ContentBlock(
                kind=str(block.get("kind", "text")),
                value=str(block.get("value", "")),
                mime_type=block.get("mime_type"),
            )
            for block in data.get("content_blocks", [])
        ]
        return cls(
            source_type=str(data["source_type"]),
            source_item_id=str(data["source_item_id"]),
            occurred_at=float(data["occurred_at"]),
            captured_at=float(data["captured_at"]),
            activity=SensorActivity(
                source=ActivityFacet(**dict(data.get("activity", {}).get("source", {}))),
                action=ActivityFacet(**dict(data.get("activity", {}).get("action", {}))),
                object=(
                    ActivityFacet(**dict(data.get("activity", {}).get("object", {})))
                    if data.get("activity", {}).get("object")
                    else None
                ),
                qualifiers={
                    str(key): value if isinstance(value, (str, int, float, bool)) else str(value)
                    for key, value in dict(data.get("activity", {}).get("qualifiers", {})).items()
                },
            ),
            narration=SensorNarration(
                body=str(data.get("narration", {}).get("body", "")),
                title=(
                    str(data.get("narration", {}).get("title", ""))
                    if data.get("narration", {}).get("title") is not None
                    else None
                ),
            ),
            content_blocks=blocks,
            raw_payload_ref=data.get("raw_payload_ref"),
            pinned_payload=data.get("pinned_payload"),
            promotion_override=data.get("promotion_override"),
            tags=list(data.get("tags", [])),
            entities=list(data.get("entities", [])),
            provenance=dict(data.get("provenance", {})),
            domain_payload=dict(data.get("domain_payload", {})),
            timeline_presentation=_timeline_presentation_from_dict(
                data.get("timeline_presentation")
            ),
        )


@dataclass(slots=True)
class SensorOutputMetadata:
    """Extracted metadata for a sensor output item."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    # Tags are classification/search labels only. Do not use tags, weak
    # co-occurrence, or category membership as evidence that the user likes or
    # believes something; emit a fact_hints item only when the source has a
    # stable, explainable fact.
    tags: list[str] = field(default_factory=list)
    # Preferred L2 structured-fact path. The host validates fact_kind,
    # predicate, origin_mode, evidence, and extraction profiles before any graph
    # write. Passive observations should usually emit interaction evidence
    # (for example VIEWED/LISTENED/USED), while durable preferences require an
    # explicit source signal such as a user-authored statement, favorites list,
    # or configuration export.
    fact_hints: list[dict[str, Any]] = field(default_factory=list)
    # Legacy/timeline compatibility path for older relation projections. New
    # sensors should prefer fact_hints for L2 cognition so source facts pass
    # through the same evidence-governed admission and conflict handling.
    relation_candidates: list[dict[str, Any]] = field(default_factory=list)


@runtime_checkable
class PluginRuntimePaths(Protocol):
    """Connection-scoped storage facade exposed to a sensor."""

    def plugin_cache_dir(self, plugin_id: str) -> Path:
        """Return this connection's state directory for its owning plugin."""


@dataclass(frozen=True, slots=True)
class ScopedSensorRuntimePaths:
    """Expose only the host-allocated state directory of one connection."""

    connection_id: str
    plugin_id: str
    state_dir: Path

    def __post_init__(self) -> None:
        if not self.state_dir.is_absolute():
            raise ValueError("Sensor state directory must be absolute")

    def plugin_cache_dir(self, plugin_id: str) -> Path:
        if plugin_id != self.plugin_id:
            raise PermissionError("Sensor cannot access another plugin's state directory")
        return self.state_dir


@dataclass(slots=True)
class SensorSyncContext:
    """One bounded pull using an explicit connection and a semantic source type."""

    connection_id: str
    source_type: str
    manual: bool
    last_cursor: Optional[str]
    last_success_at: Optional[float]
    limit: int
    runtime_paths: PluginRuntimePaths
    plugin_settings: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PullSyncSensor(Protocol):
    """Protocol for sensors returning versioned source changes."""

    supports_pull_sync: bool

    async def collect_items(self, context: SensorSyncContext) -> SourceChangeBatch:
        """Return changes; only the host may acknowledge cursor progression."""


@dataclass(slots=True)
class L2BatchPolicy:
    """Plugin-suggested L2 batching policy for one sensor output."""

    owner: str | None = None
    catch_up_owner: str | None = None
    max_events: int | None = None
    min_ready_events: int | None = None
    max_estimated_tokens: int | None = None
    max_wait_seconds: int | None = None


class SensorBase(ABC):
    """Base contract for all data collection sensors."""

    sensor_id: str = "sensor.base"
    display_name: str = "Sensor"
    source_type: str = "unknown"
    memory_event_type: str = "SENSOR_EVENT"
    supports_pull_sync: bool = False
    supports_watch_mode: bool = False
    polling_mode: str = "interval"
    default_interval: int = 15
    update_key_fields: tuple[str, ...] = ()
    memory_policy: SensorMemoryPolicy = SensorMemoryPolicy()
    relation_edge_whitelist: tuple[str, ...] = ()
    config_schema: dict[str, Any] = {}
    capabilities: dict[str, Any] = {}

    def __init__(self) -> None:
        self._plugin_id: str | None = None
        self._plugin_dir: Path | None = None
        self._i18n: PluginI18n | None = None
        self.connection: PluginConnection | None = None
        self.context: PluginContext | None = None

    def bind_plugin_context(
        self,
        *,
        connection: PluginConnection,
        context: PluginContext,
        plugin_id: str | None = None,
        plugin_dir: str | Path | None = None,
    ) -> None:
        """Bind the connection authority and its private authoring context."""
        if context.connection != connection or (plugin_id and plugin_id != connection.plugin_id):
            raise ValueError("Sensor connection context identity mismatch")
        self.connection = connection
        self.context = context
        self._plugin_id = connection.plugin_id
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
        """Look up a translated string for this sensor's plugin."""
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
        """Return a producer-side stable item identity for deduplication."""
        identity_parts = [str(item.get(field_name, "")) for field_name in self.update_key_fields]
        return ":".join(identity_parts)

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        """Return a fingerprint used to detect changes in seen items."""
        payload = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def discover_changes(
        self,
        items: list[dict[str, Any]],
        known_fingerprints: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter source items by version fingerprint."""
        known = known_fingerprints or set()
        return [item for item in items if self.source_item_version_fingerprint(item) not in known]

    @abstractmethod
    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        """Convert a source item into a domain-neutral sensor output."""

    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        """Extract entities, tags, fact hints, and relation candidates from a source item."""
        return SensorOutputMetadata()

    async def collect_items(self, context: SensorSyncContext) -> SourceChangeBatch:
        """Pull-sync entry point for sensors that support active collection."""
        _ = context
        raise NotImplementedError(f"{self.sensor_id} does not implement pull sync")

    def build_change_batch(
        self,
        items: list[dict[str, Any]],
        *,
        next_cursor: str | None = None,
        complete: bool = True,
        watermark_ts: float | None = None,
        stats: dict[str, Any] | None = None,
    ) -> SourceChangeBatch:
        """Build explicit upserts using the source's stable identity and version."""
        return SourceChangeBatch(
            changes=[
                SourceChange(
                    object_id=self.source_item_identity(item),
                    version=self.source_item_version_fingerprint(item),
                    payload=item,
                )
                for item in items
            ],
            next_cursor=next_cursor,
            complete=complete,
            watermark_ts=watermark_ts,
            stats=dict(stats or {}),
        )

    async def clear_user_content(self, context: UserContentClearContext) -> None:
        """Erase sensor-owned local user content during a full product clear.

        Override this when the sensor retains collected or derived payloads,
        pending batches, or other user content outside host stores. Preserve
        source-only cursors and watermarks together with plugin settings,
        credentials, and connected-account state. The hook must be local-only,
        idempotent, and must not perform network I/O.

        The default is a safe no-op for stateless sensors.
        """
        _ = context

    async def fetch_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Optional pre-processing/enrichment before build_output."""
        return dict(item)

    def l2_batch_policy(self, output: SensorOutput) -> L2BatchPolicy | None:
        """Return an optional advisory L2 batching policy for sensor events."""
        _ = output
        return None

    def idempotency_key(self, output: SensorOutput) -> str | None:
        """Return an optional business-level idempotency key for sensor events."""
        value = str(output.source_item_id or "").strip()
        return value or None

    def _build_activity_facet(
        self,
        *,
        code: str,
        i18n_key: str,
        fallback: str,
        embedding_fallback: str | None = None,
    ) -> ActivityFacet:
        """Return one activity facet for a sensor output."""
        return ActivityFacet(
            code=str(code).strip(),
            i18n_key=str(i18n_key).strip(),
            fallback=str(fallback).strip(),
            embedding_fallback=(
                str(embedding_fallback).strip()
                if embedding_fallback is not None
                else None
            ),
        )

    def _build_activity(
        self,
        *,
        source: ActivityFacet,
        action: ActivityFacet,
        object: ActivityFacet | None = None,
        qualifiers: dict[str, Any] | None = None,
    ) -> SensorActivity:
        """Return the structured activity envelope for a sensor output."""
        def _coerce_qualifier_value(value: Any) -> Any:
            # Preserve JSON-native primitives. Strings get an empty-check
            # downstream; numerics/bools always round-trip cleanly through
            # the JSON metadata column.
            if isinstance(value, (int, float, bool)):
                return value
            return str(value)

        normalized_qualifiers: dict[str, str | int | float | bool] = {}
        for raw_key, raw_value in dict(qualifiers or {}).items():
            key = str(raw_key).strip()
            if not key:
                continue
            coerced = _coerce_qualifier_value(raw_value)
            if isinstance(coerced, str) and not coerced.strip():
                continue
            normalized_qualifiers[key] = coerced
        return SensorActivity(
            source=source,
            action=action,
            object=object,
            qualifiers=normalized_qualifiers,
        )

    def _build_narration(
        self,
        *,
        body: str,
        title: str | None = None,
    ) -> SensorNarration:
        """Return the factual narration envelope for a sensor output."""
        normalized_title = str(title).strip() if title is not None else None
        return SensorNarration(
            body=str(body).strip(),
            title=normalized_title or None,
        )

    def _build_output(
        self,
        *,
        source_item_id: str,
        activity: SensorActivity,
        narration: SensorNarration,
        occurred_at: float | None = None,
        raw_payload_ref: str | None = None,
        content_blocks: list[ContentBlock] | None = None,
        tags: list[str] | None = None,
        provenance: dict[str, Any] | None = None,
        domain_payload: dict[str, Any] | None = None,
        timeline_presentation: TimelinePresentation | None = None,
    ) -> SensorOutput:
        """Convenience builder analogous to the legacy timeline sensor helper."""
        now = time.time()
        return SensorOutput(
            source_type=self.source_type,
            source_item_id=source_item_id,
            occurred_at=float(occurred_at or now),
            captured_at=now,
            activity=activity,
            narration=narration,
            raw_payload_ref=raw_payload_ref,
            content_blocks=list(content_blocks or []),
            tags=list(tags or []),
            provenance=provenance or {"sensor_id": self.sensor_id},
            domain_payload=domain_payload or {},
            timeline_presentation=timeline_presentation or TimelinePresentation(),
        )


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _timeline_presentation_from_dict(value: Any) -> TimelinePresentation:
    if isinstance(value, TimelinePresentation):
        return value
    if not isinstance(value, dict):
        return TimelinePresentation()
    return TimelinePresentation(
        mode=str(value.get("mode") or "full"),
        title=value.get("title"),
        summary=value.get("summary"),
    )


__all__ = [
    "ActivityFacet",
    "ContentBlock",
    "L2BatchPolicy",
    "PluginRuntimePaths",
    "PullSyncSensor",
    "SensorBase",
    "SensorActivity",
    "SensorMemoryPolicy",
    "SensorNarration",
    "SensorOutput",
    "SensorOutputMetadata",
    "SensorSpec",
    "SensorSyncContext",
    "ScopedSensorRuntimePaths",
    "SourceChange",
    "SourceChangeBatch",
    "TimelinePresentation",
]
