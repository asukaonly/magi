"""Atomic, serialized persistence for the center's recent workspace choices."""

import asyncio
import json
from pathlib import Path
import threading

from magi_plugin_sdk.fs import atomic_write_managed_text, read_managed_text


class JsonRecentWorkspaceRepository:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    async def list_paths(self) -> list[str]:
        return await asyncio.to_thread(self._load_locked)

    async def remember(self, path: str) -> list[str]:
        normalized = path.strip()
        if not normalized:
            raise ValueError("Path is required")
        if len(normalized) > 4096:
            raise ValueError("Workspace path is too long")
        return await asyncio.to_thread(self._remember_locked, normalized)

    def _load(self) -> list[str]:
        raw = read_managed_text(self._path, max_bytes=32768)
        if raw is None:
            return []
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("paths"), list):
            raise ValueError("Stored workspace preferences are invalid")
        paths = data["paths"]
        if not all(isinstance(path, str) for path in paths):
            raise ValueError("Stored workspace paths must be strings")
        return list(dict.fromkeys(path.strip() for path in paths if path.strip()))[:5]

    def _load_locked(self) -> list[str]:
        with self._lock:
            return self._load()

    def _remember_locked(self, path: str) -> list[str]:
        with self._lock:
            paths = [path, *[item for item in self._load() if item != path]][:5]
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_managed_text(self._path, json.dumps({"paths": paths}, ensure_ascii=False))
            return paths
