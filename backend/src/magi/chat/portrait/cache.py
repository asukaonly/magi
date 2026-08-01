"""LRU cache for persona portraits with TTL + optional disk persistence.

Keyed by ``(session_id, conversation_hash, persona_id)``. The disk layer
persists the **latest successful** payload per key across process restarts
so the chat shell rail reappears immediately on app reopen instead of
flashing back to the cold-start placeholder.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Tuple

from magi_plugin_sdk.fs import (
    list_managed_directory_names,
    path_is_link,
    remove_managed_file,
)

from .contracts import ChatPortraitObservation, ChatPortraitPayload

CacheKey = Tuple[str, str, str]


logger = logging.getLogger(__name__)


class PortraitCache:
    """Thread-safe LRU cache supporting stale-while-revalidate.

    Every successful payload is stored with a timestamp:
    - :meth:`get` returns the payload only if it is within TTL ("fresh").
    - :meth:`get_stale` returns the payload regardless of TTL, as long as
      it has not been LRU-evicted. Callers use this to keep displaying the
      previous portrait while a background task computes the next one.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_entries: int = 256,
        persistence_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._data: OrderedDict[CacheKey, tuple[float, ChatPortraitPayload]] = OrderedDict()
        self._lock = RLock()
        self._persistence_path: Path | None = Path(persistence_path) if persistence_path else None
        if self._persistence_path is not None:
            self._load_from_disk()

    def get(self, key: CacheKey) -> ChatPortraitPayload | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, payload = entry
            if time.monotonic() - ts > self._ttl:
                # Expired — fresh lookup must miss, but keep the entry for
                # stale-while-revalidate fallback.
                return None
            self._data.move_to_end(key)
            return payload

    def get_stale(self, key: CacheKey) -> ChatPortraitPayload | None:
        """Return the entry ignoring TTL. ``None`` only if never set or evicted."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            self._data.move_to_end(key)
            return entry[1]

    def set(self, key: CacheKey, payload: ChatPortraitPayload) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), payload)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
            self._save_to_disk_locked()

    def invalidate_persona(self, persona_id: str) -> None:
        with self._lock:
            stale = [k for k in self._data if k[2] == persona_id]
            for k in stale:
                self._data.pop(k, None)
            self._save_to_disk_locked()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._delete_persistence_locked()

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> None:
        path = self._persistence_path
        if path is None or not path.exists():
            return
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception as exc:
            logger.warning("portrait cache load failed (%s): %s", path, exc)
            return
        if not isinstance(data, list):
            return
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                key_parts = entry["key"]
                payload_dict = entry["payload"]
                key: CacheKey = (
                    str(key_parts[0]),
                    str(key_parts[1]),
                    str(key_parts[2]),
                )
                payload = _payload_from_dict(payload_dict)
            except Exception as exc:
                logger.debug("portrait cache skip malformed entry: %s", exc)
                continue
            # Loaded entries get a fresh monotonic timestamp; the absolute
            # `generated_at` inside the payload preserves the original.
            self._data[key] = (time.monotonic(), payload)
        # LRU cap.
        while len(self._data) > self._max:
            self._data.popitem(last=False)
        logger.info("portrait cache loaded %d entries from %s", len(self._data), path)

    def _save_to_disk_locked(self) -> None:
        path = self._persistence_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = [
                {"key": list(key), "payload": payload.to_dict()}
                for key, (_, payload) in self._data.items()
            ]
            payload_text = json.dumps(snapshot, ensure_ascii=False)
            # Atomic write: tmp file in same dir, then rename.
            fd, tmp_name = tempfile.mkstemp(
                prefix=".portrait-cache-",
                suffix=".json",
                dir=str(path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload_text)
                os.replace(tmp_name, path)
            except Exception:
                # Clean up the temp file on failure.
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("portrait cache save failed (%s): %s", path, exc)

    def _delete_persistence_locked(self) -> None:
        path = self._persistence_path
        if path is None:
            return
        try:
            clear_persisted_portrait_cache(path)
        except OSError as exc:
            logger.warning("portrait cache delete failed (%s): %s", path, exc)
            raise


def clear_persisted_portrait_cache(
    persistence_path: str | os.PathLike[str],
) -> int:
    """Remove portrait cache entries without following managed links."""
    path = Path(persistence_path)
    parent = path.parent
    try:
        parent_stat = os.lstat(parent)
    except FileNotFoundError:
        return 0
    if path_is_link(parent, path_stat=parent_stat) or not stat.S_ISDIR(parent_stat.st_mode):
        return int(remove_managed_file(parent))

    candidates = [path]
    candidates.extend(
        parent / name
        for name in list_managed_directory_names(parent)
        if name.startswith(".portrait-cache-") and name.endswith(".json")
    )
    deleted = 0
    for candidate in candidates:
        if remove_managed_file(candidate):
            deleted += 1
    return deleted


def _payload_from_dict(data: dict) -> ChatPortraitPayload:
    observations_raw = data.get("observations") or []
    observations: list[ChatPortraitObservation] = []
    for obs in observations_raw:
        if not isinstance(obs, dict):
            continue
        observations.append(
            ChatPortraitObservation(
                kind=str(obs.get("kind") or "reflection"),  # type: ignore[arg-type]
                text=str(obs.get("text") or ""),
                basis_count=int(obs.get("basis_count") or 0),
                basis_summary=str(obs.get("basis_summary") or ""),
                basis_refs=[str(r) for r in (obs.get("basis_refs") or []) if r],
            )
        )
    return ChatPortraitPayload(
        session_id=str(data.get("session_id") or ""),
        persona_id=str(data.get("persona_id") or ""),
        topic=str(data.get("topic") or ""),
        generated_at=int(data.get("generated_at") or 0),
        observations=observations,
        is_cold_start=bool(data.get("is_cold_start")),
        cold_start_line=data.get("cold_start_line"),
        cold_start_reason=data.get("cold_start_reason"),
        is_stale=bool(data.get("is_stale")),
    )
