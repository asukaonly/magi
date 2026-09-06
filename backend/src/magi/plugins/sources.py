"""Source contribution contracts and registry."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import threading
from typing import Any, Optional

from .contracts import PluginContribution
from magi_plugin_sdk.sources import SourceSpec  # noqa: F401


@dataclass(frozen=True, slots=True)
class RegisteredSourceSnapshot:
    """Stable identity and instance for one registered source contribution."""

    plugin_id: str
    source_id: str
    source: Any
    connection_id: str | None = None


class SourceRegistry:
    """Registry for runtime source contributions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sources: dict[str, Any] = {}
        self._specs: dict[str, SourceSpec] = {}
        self._plugin_ownership: dict[str, str] = {}
        self._registration_tokens: dict[str, object] = {}

    def register(
        self, plugin_id: str, source_id: str, source: Any, spec: SourceSpec
    ) -> Callable[[], None]:
        if source_id != spec.source_id:
            raise ValueError("Source tuple id must match its spec")
        token = object()
        with self._lock:
            if source_id in self._sources:
                raise ValueError(f"Source already registered: {source_id}")
            self._sources[source_id] = source
            self._specs[source_id] = spec
            self._plugin_ownership[source_id] = plugin_id
            self._registration_tokens[source_id] = token

        def dispose() -> None:
            with self._lock:
                if self._registration_tokens.get(source_id) is token:
                    self.unregister(source_id, plugin_id=plugin_id)

        return dispose

    def unregister(self, source_id: str, *, plugin_id: str) -> bool:
        with self._lock:
            if self._plugin_ownership.get(source_id) != plugin_id:
                return False
            self._sources.pop(source_id, None)
            self._specs.pop(source_id, None)
            self._plugin_ownership.pop(source_id, None)
            self._registration_tokens.pop(source_id, None)
            return True

    def get_source(self, source_id: str) -> Optional[Any]:
        with self._lock:
            return self._sources.get(source_id)

    def get_spec(self, source_id: str) -> Optional[SourceSpec]:
        with self._lock:
            return self._specs.get(source_id)

    def list_specs(self, *, domain: Optional[str] = None) -> list[SourceSpec]:
        with self._lock:
            specs = list(self._specs.values())
        if domain is not None:
            specs = [spec for spec in specs if spec.domain == domain]
        return specs

    def resolve_domain_source(
        self, domain: str, source_type: str, *, connection_id: str | None = None
    ) -> tuple[str, str, Any, SourceSpec] | None:
        with self._lock:
            matches = []
            for source_id, source in self._sources.items():
                spec = self._specs[source_id]
                candidate = str(
                    spec.metadata.get("source_type") or getattr(source, "source_type", "")
                )
                if (
                    spec.domain == domain
                    and candidate == source_type
                    and (
                        connection_id is None or spec.metadata.get("connection_id") == connection_id
                    )
                ):
                    matches.append(
                        (self._plugin_ownership.get(source_id, ""), source_id, source, spec)
                    )
            if len(matches) > 1:
                raise ValueError("Domain source lookup requires an unambiguous connection id")
            return matches[0] if matches else None

    def resolve_source(
        self, source_type: str, *, connection_id: str | None = None
    ) -> tuple[str, str, Any, SourceSpec] | None:
        with self._lock:
            matches = []
            for source_id, source in self._sources.items():
                spec = self._specs[source_id]
                candidate = str(
                    spec.metadata.get("source_type") or getattr(source, "source_type", "")
                )
                if candidate == source_type and (
                    connection_id is None or spec.metadata.get("connection_id") == connection_id
                ):
                    matches.append(
                        (self._plugin_ownership.get(source_id, ""), source_id, source, spec)
                    )
            if len(matches) > 1:
                raise ValueError("Source lookup requires an unambiguous connection id")
            return matches[0] if matches else None

    def list_contributions(self, plugin_id: Optional[str] = None) -> list[PluginContribution]:
        with self._lock:
            contributions: list[PluginContribution] = []
            for source_id, spec in self._specs.items():
                owner = self._plugin_ownership.get(source_id, "")
                if plugin_id is not None and owner != plugin_id:
                    continue
                contributions.append(
                    PluginContribution(
                        plugin_id=owner,
                        contribution_id=source_id,
                        contribution_type="source",
                        display_name=spec.display_name,
                        description=spec.description,
                        surface=spec.surface
                        if spec.surface in {"extensions", "tools", "timeline"}
                        else "extensions",
                        fields=list(spec.fields),
                        metadata={
                            "domain": spec.domain,
                            "sync_mode": spec.sync_mode,
                            "polling_mode": spec.polling_mode,
                            **dict(spec.metadata),
                        },
                    )
                )
            return contributions

    def snapshot_user_content_clear_targets(self) -> tuple[RegisteredSourceSnapshot, ...]:
        """Return a stable source snapshot for one host clear operation."""

        with self._lock:
            return tuple(
                RegisteredSourceSnapshot(
                    plugin_id=self._plugin_ownership.get(source_id, ""),
                    source_id=source_id,
                    source=source,
                    connection_id=self._specs[source_id].metadata.get("connection_id"),
                )
                for source_id, source in sorted(self._sources.items())
            )


__all__ = ["RegisteredSourceSnapshot", "SourceRegistry", "SourceSpec"]
