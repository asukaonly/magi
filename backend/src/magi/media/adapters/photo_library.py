"""PhotoLibraryMediaSource — exposes photo-library plugin events as a MediaSource.

The plugin itself (plugins/photo-library/) writes L1 events with
source="photo_library" carrying asset refs and EXIF metadata. This
adapter reads those events through the L1 store's query_events API and
shapes them into the {ref, timestamp, ...} dicts the MediaSelector expects.

The adapter is intentionally tolerant of missing fields: any event that
doesn't carry a stable asset_ref is silently skipped (rather than crashing
the registry's collect_assets fan-out).
"""

from __future__ import annotations

from typing import Any, Protocol


class _L1StoreProtocol(Protocol):
    async def query_events(self, **kwargs) -> list[dict[str, Any]]: ...


class PhotoLibraryMediaSource:
    """MediaSource adapter over photo_library L1 events."""

    source_id = "photo-library"

    def __init__(self, *, l1_store: _L1StoreProtocol) -> None:
        self._l1_store = l1_store

    async def list_assets(self, *, start: float, end: float) -> list[dict]:
        try:
            events = await self._l1_store.query_events(
                source_filters=["photo_library"],
                start_time=start,
                end_time=end,
                limit=500,
            )
        except Exception:
            # If L1 is unavailable, return empty rather than crashing the
            # MediaSourceRegistry fan-out across all sources.
            return []

        out: list[dict] = []
        for ev in events or []:
            ref = self._extract_asset_ref(ev)
            if not ref:
                continue
            ts = float(ev.get("timestamp") or 0.0)
            metadata = ev.get("metadata") or {}
            entry: dict = {
                "ref": ref,
                "timestamp": ts,
            }
            mime = ev.get("mime_type")
            if mime is not None:
                entry["mime_type"] = mime
            if isinstance(metadata, dict):
                # Surface known keys at the top level for selector convenience.
                for key in ("location", "people", "tags"):
                    if key in metadata:
                        entry[key] = metadata[key]
            out.append(entry)
        return out

    @staticmethod
    def _extract_asset_ref(event: dict) -> str | None:
        """Defensive extraction. Looks at common locations.

        Adapt as the plugin's L1 event schema evolves.
        """
        # Top-level asset_ref
        ref = event.get("asset_ref")
        if isinstance(ref, str) and ref.strip():
            return ref.strip()

        # First content_block with a usable ref/value
        content_blocks = event.get("content_blocks")
        if isinstance(content_blocks, list) and content_blocks:
            first = content_blocks[0]
            if isinstance(first, dict):
                candidate = first.get("ref") or first.get("value")
                if isinstance(candidate, str) and candidate.startswith("photo-library://"):
                    return candidate.strip()

        return None
