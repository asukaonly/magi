"""Registry for parser-only, one-shot history importer contributions."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import threading

from magi_plugin_sdk import HistoryImporter, HistoryImporterSpec


@dataclass(frozen=True, slots=True)
class RegisteredHistoryImporter:
    plugin_id: str
    importer_id: str
    importer: HistoryImporter
    spec: HistoryImporterSpec
    connection_id: str | None = None


class HistoryImporterRegistry:
    """Process-local registry keyed by package and importer identity."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str | None, str], RegisteredHistoryImporter] = {}
        self._lock = threading.RLock()

    def register(
        self,
        *,
        plugin_id: str,
        importer_id: str,
        importer: HistoryImporter,
        spec: HistoryImporterSpec,
        connection_id: str | None = None,
    ) -> Callable[[], None]:
        if importer_id != spec.importer_id:
            raise ValueError("History importer tuple id must match its spec")
        if not callable(getattr(importer, "parse", None)):
            raise TypeError("History importer must implement parse(paths)")
        key = (plugin_id, connection_id, importer_id)
        with self._lock:
            if key in self._entries:
                raise ValueError(f"History importer already registered: {plugin_id}/{importer_id}")
            self._entries[key] = RegisteredHistoryImporter(
                plugin_id=plugin_id,
                importer_id=importer_id,
                importer=importer,
                spec=spec,
                connection_id=connection_id,
            )
            entry = self._entries[key]

        def dispose() -> None:
            with self._lock:
                if self._entries.get(key) is entry:
                    self._entries.pop(key)

        return dispose

    def unregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for key in [key for key in self._entries if key[0] == plugin_id]:
                self._entries.pop(key, None)

    def get(
        self, plugin_id: str, importer_id: str, *, connection_id: str | None = None
    ) -> RegisteredHistoryImporter | None:
        with self._lock:
            if connection_id is not None:
                return self._entries.get((plugin_id, connection_id, importer_id))
            matches = [
                entry
                for entry in self._entries.values()
                if entry.plugin_id == plugin_id and entry.importer_id == importer_id
            ]
            if len(matches) > 1:
                raise ValueError("History importer lookup requires a connection id")
            return matches[0] if matches else None

    def list(self) -> list[RegisteredHistoryImporter]:
        with self._lock:
            return sorted(
                self._entries.values(),
                key=lambda item: (item.plugin_id, item.connection_id or "", item.importer_id),
            )


__all__ = ["HistoryImporterRegistry", "RegisteredHistoryImporter"]
