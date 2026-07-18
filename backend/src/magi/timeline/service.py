"""Timeline service facade over memory-backed viewport and context bundles."""

from __future__ import annotations

import mimetypes
from typing import Any, Optional
from urllib.parse import unquote

from magi.events.sensor_activity_snapshot import activity_snapshot_from_metadata

from .. import i18n as core_i18n
from ..core.sqlite import sqlite_connection_async
from ..media.adapters.photo_library import PHOTO_LIBRARY_SOURCE_FILTERS
from ..memory.source_event_governance import (
    source_occurrence_visible_predicate,
)
from .contracts import TimelineEvent
from .cover_store import (
    TIMELINE_COVER_ASSET_SOURCES,
    TimelineCoverAssetSource,
    TimelineCoverPreferenceStore,
)
from .insight_pipeline import TimelineInsightPipeline
from .viewport_builder import TimelineViewportBuilder

_WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


async def _manual_asset_is_referenced(*, db_path: str, asset_ref: str) -> bool:
    """Allow manual assets only while a user-visible owner still references them."""
    async with sqlite_connection_async(db_path) as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
            tables = {str(row[0]) for row in await cursor.fetchall()}

        checks: list[tuple[str, tuple[str, ...]]] = []
        if "manual_entries" in tables:
            time_range_visibility = source_occurrence_visible_predicate(
                "entry.event_at",
                barrier_alias="manual_asset_forget_range",
            )
            checks.append(
                (
                    f"""
                    SELECT 1 FROM manual_entries AS entry
                    WHERE entry.deleted_at IS NULL
                      AND entry.delete_requested_at IS NULL
                      AND (
                          entry.pending_l1_event_id IS NULL
                          OR entry.pending_l1_predecessor_event_id IS NULL
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM json_each(CASE
                              WHEN json_valid(entry.attachments_json)
                                  THEN entry.attachments_json
                              ELSE '[]'
                          END) AS attachment
                          WHERE CAST(attachment.value AS TEXT) = ?
                      )
                      AND {time_range_visibility}
                    LIMIT 1
                    """,
                    (asset_ref,),
                )
            )
        if "experiences" in tables:
            checks.append(
                (
                    """
                    SELECT 1 FROM experiences
                    WHERE status != 'invalidated' AND user_cover_asset_ref = ?
                    LIMIT 1
                    """,
                    (asset_ref,),
                )
            )
        if "experience_drafts" in tables:
            checks.append(
                (
                    """
                    SELECT 1 FROM experience_drafts
                    WHERE user_cover_asset_ref = ?
                    LIMIT 1
                    """,
                    (asset_ref,),
                )
            )
        if "timeline_cover_preferences" in tables:
            checks.append(
                (
                    """
                    SELECT 1 FROM timeline_cover_preferences
                    WHERE mode = 'asset'
                      AND source IN ('current_period', 'custom_upload')
                      AND asset_ref = ?
                    LIMIT 1
                    """,
                    (asset_ref,),
                )
            )

        for query, args in checks:
            async with db.execute(query, args) as cursor:
                if await cursor.fetchone() is not None:
                    return True
    return False


def _synthesize_standout_title(time_start: float, time_end: float) -> str:
    """Build a readable fallback title from time + duration metadata.

    Used when an episode has no slice_narrative, user_label, or label.
    Format: "周日 14:00 · 3h" (no source/topic info — that would require
    pulling them from the row, which the caller can add later if needed).
    """
    from datetime import datetime

    # Local time — the standout list above formats `date` in local time
    # for the same reason (server tz = user tz for desktop deployment).
    # Mixing UTC here would put the title's "14:00" 8 hours off from
    # the "date" it's stamped under for non-UTC users.
    dt = datetime.fromtimestamp(time_start)
    weekday = _WEEKDAY_LABELS[dt.weekday()]
    hh_mm = dt.strftime("%H:%M")

    duration_seconds = max(0.0, time_end - time_start)
    if duration_seconds >= 3600:
        hours = duration_seconds / 3600.0
        duration_label = f"{hours:.0f}h" if hours >= 2 else f"{hours:.1f}h"
    elif duration_seconds >= 60:
        minutes = int(duration_seconds // 60)
        duration_label = f"{minutes}m"
    else:
        duration_label = "短"

    return f"周{weekday} {hh_mm} · {duration_label}"


async def _resolve_photo_library_asset(asset_ref: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve a photo-library:// ref to (file_path, content_type).

    Plan 3 ships a minimal resolver that returns (None, None). Plan 4 (or a
    later integration step) will plug in the photo-library plugin's actual
    reader once a stable host-callable resolve API is exposed.

    Tests monkeypatch this function at the module level.
    """
    return None, None


def _photo_metadata(event: dict[str, Any]) -> dict[str, Any]:
    for key in ("metadata", "metadata_json"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _iter_representative_photos(metadata: dict[str, Any]):
    photos = metadata.get("representative_photos")
    if not isinstance(photos, list):
        return
    for photo in photos:
        if isinstance(photo, dict):
            yield photo


def _photo_library_asset_id(asset_ref: str) -> str:
    scheme, _, tail = asset_ref.partition("://")
    if scheme != "photo-library":
        return ""
    return tail.strip()


def _guess_image_content_type(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith((".heic", ".heif")):
        return "image/heic"
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


class TimelineService:
    """Provides timeline-oriented operations over unified memory."""

    def __init__(
        self, unified_memory, *, location_resolver=None, manual_entry_asset_store=None
    ) -> None:
        self._unified_memory = unified_memory
        self._manual_entry_asset_store = manual_entry_asset_store
        memory_db_path = getattr(unified_memory, "memory_db_path", None)
        self._cover_store = (
            TimelineCoverPreferenceStore(db_path=str(memory_db_path)) if memory_db_path else None
        )
        self._insight_pipeline = TimelineInsightPipeline(unified_memory)
        self._viewport_builder = TimelineViewportBuilder(
            l1_store=getattr(unified_memory, "l1", None),
            l2_store=getattr(unified_memory, "l2", None),
            l3_store=getattr(unified_memory, "l3", None),
            l4_store=getattr(unified_memory, "l4", None),
            entity_catalog=getattr(unified_memory, "l2_entity_catalog", None),
            location_resolver=location_resolver,
        )

    async def upsert_event(
        self,
        event: TimelineEvent,
        *,
        relation_candidates: Optional[list[dict]] = None,
        allowed_edge_whitelist: Optional[list[str]] = None,
    ) -> str:
        # Sensor outputs are already persisted into L1 by SensorIngestionGateway.
        # Re-ingesting them here would create a second derived memory record and
        # enqueue duplicate L2 work for the same source item.
        event.processing_status["stored"] = True
        if relation_candidates:
            persisted = await self._insight_pipeline.process_event(
                event,
                relation_candidates,
                allowed_edge_whitelist or [],
            )
            event.processing_status["analyzed"] = True
            event.processing_status["persisted_relations"] = len(persisted)
        return event.event_id

    async def get_viewport(
        self,
        *,
        scale: str,
        start: float,
        end: float,
        query: str | None = None,
        timezone: str | None = None,
        focus: str = "self",
        locale: str = "en",
    ) -> dict:
        viewport = await self._viewport_builder.build_viewport(
            scale=scale,
            start=start,
            end=end,
            query=query,
            timezone=timezone,
            focus=focus,
            locale=locale,
        )
        viewport["cover"] = await self._resolve_cover_state(
            viewport=viewport,
            scale=scale,
            start=start,
            end=end,
        )
        return viewport

    async def set_cover_preference(
        self,
        *,
        scale: str,
        start: float,
        end: float,
        mode: str,
        asset_ref: str | None = None,
        source: TimelineCoverAssetSource = "current_period",
        locale: str = "en",
    ) -> dict[str, Any]:
        if self._cover_store is None:
            raise RuntimeError("Timeline cover preferences are unavailable")
        if source not in TIMELINE_COVER_ASSET_SOURCES:
            raise ValueError(f"Unsupported timeline cover source: {source}")

        viewport = await self._viewport_builder.build_viewport(
            scale=scale,
            start=start,
            end=end,
            query=None,
            timezone=None,
            focus="self",
            locale=locale,
        )
        candidates = self._cover_candidates_from_viewport(viewport)

        if mode == "auto":
            await self._cover_store.clear_preference(
                scale=scale, period_start=start, period_end=end
            )
            return self._cover_state_from_preference(candidates=candidates, preference=None)

        if mode == "asset":
            normalized_asset_ref = (asset_ref or "").strip()
            if not normalized_asset_ref:
                raise ValueError("asset_ref is required")
            if source == "current_period":
                candidate_refs = {str(item.get("asset_ref") or "") for item in candidates}
                if normalized_asset_ref not in candidate_refs:
                    raise ValueError("asset_ref is not available in the current timeline period")
            elif (
                self._manual_entry_asset_store is None
                or not self._manual_entry_asset_store.has_asset(normalized_asset_ref)
            ):
                raise ValueError("asset_ref is not an available custom upload")
            preference = await self._cover_store.set_preference(
                scale=scale,
                period_start=start,
                period_end=end,
                mode="asset",
                asset_ref=normalized_asset_ref,
                source=source or "current_period",
            )
            return self._cover_state_from_preference(candidates=candidates, preference=preference)

        if mode == "hidden":
            preference = await self._cover_store.set_preference(
                scale=scale,
                period_start=start,
                period_end=end,
                mode="hidden",
            )
            return self._cover_state_from_preference(candidates=candidates, preference=preference)

        raise ValueError(f"Unsupported timeline cover mode: {mode}")

    async def list_standout(
        self,
        *,
        period_start: Optional[float],
        period_end: Optional[float],
        limit: int = 50,
    ) -> list[dict]:
        """List standout episodes — Magi-curated + user-pinned — for the sidebar.

        Returns serializable dicts shaped for the GET /timeline/standout payload.
        """
        from datetime import datetime

        store = getattr(self._unified_memory, "l2", None)
        if store is None:
            return []

        rows = await store.list_standout_episodes(
            period_start=period_start,
            period_end=period_end,
            limit=limit,
        )
        items: list[dict] = []
        for r in rows:
            ts = float(r.get("time_start") or 0.0)
            te = float(r.get("time_end") or ts)
            # Title fallback chain:
            #   slice_narrative (LLM-written sentence, available after diary scheduler runs)
            #   → user_label (manual)
            #   → label (rule-based, usually empty)
            #   → synthetic ("周日 14:00 · 3h" derived from time + duration)
            title = (
                str(r.get("slice_narrative") or "").strip()
                or str(r.get("user_label") or "").strip()
                or str(r.get("label") or "").strip()
                or _synthesize_standout_title(ts, te)
            )
            items.append(
                {
                    "episode_id": r["episode_id"],
                    "scale": "day",
                    "start": ts,
                    "end": te,
                    "title": title,
                    # Format in the server's local timezone. For magi's
                    # desktop-app deployment, server tz = user tz, so this
                    # matches the user's day boundary. This is the same
                    # convention daily_mood_aggregate's day_local_date uses
                    # — keep them aligned so the sidebar standout list and
                    # mood calendar pin events to the same calendar day.
                    # (If we ever multi-user this server-side, a tz query
                    # param will be needed.)
                    "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "source": "user" if r.get("user_pinned") else "magi",
                    "score": float(r.get("standout_score") or 0.0),
                }
            )
        return items

    async def list_mood_calendar(self, *, month: str) -> dict:
        """Sidebar mood calendar payload for a YYYY-MM month.

        Days with no daily_mood_aggregate row are omitted; the frontend
        renders empty cells for missing dates.
        """
        from calendar import monthrange
        from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore

        try:
            year, mo = (int(p) for p in month.split("-", 1))
            last_day = monthrange(year, mo)[1]
        except (ValueError, OverflowError):
            return {"month": month, "days": [], "error": "invalid_month"}

        db_path = getattr(self._unified_memory, "memory_db_path", None)
        if db_path is None:
            return {"month": month, "days": []}

        store = DailyMoodAggregateStore(db_path=str(db_path))
        start_date = f"{year:04d}-{mo:02d}-01"
        end_date = f"{year:04d}-{mo:02d}-{last_day:02d}"
        rows = await store.list_aggregates(start_date=start_date, end_date=end_date)

        return {
            "month": month,
            "days": [
                {
                    "date": r.day_local_date,
                    "dominant_valence": r.dominant_valence,
                    "volatility": r.volatility_score,
                    "event_count": r.event_count,
                    "sparkline": r.state_curve_compact,
                }
                for r in rows
            ],
        }

    async def serve_asset(self, *, asset_ref: str) -> Optional[tuple[bytes, str]]:
        """Resolve an asset_ref and read its bytes from disk.

        Returns (bytes, content_type) on success, None when the ref is empty,
        unrecognized, or the file is missing. The route turns None into 404.

        Currently routes two schemes:
          - ``photo-library://...``      from the photo-library plugin
          - ``manual-entry-asset://...`` from user-uploaded entry images
        """
        if not asset_ref:
            return None

        asset_ref = unquote(asset_ref)
        scheme, _, _ = asset_ref.partition("://")

        if scheme == "manual-entry-asset":
            if self._manual_entry_asset_store is None:
                return None
            memory_db_path = str(getattr(self._unified_memory, "memory_db_path", "") or "").strip()
            if not memory_db_path or not await _manual_asset_is_referenced(
                db_path=memory_db_path,
                asset_ref=asset_ref,
            ):
                return None
            return self._manual_entry_asset_store.resolve(asset_ref)

        if scheme == "photo-library":
            file_path, content_type = await self._resolve_photo_library_asset_from_l1(asset_ref)
            if not file_path:
                file_path, content_type = await _resolve_photo_library_asset(asset_ref)
            if not file_path:
                return None
            try:
                with open(file_path, "rb") as fh:
                    data = fh.read()
            except OSError:
                return None
            return data, content_type or "application/octet-stream"

        return None

    async def _resolve_cover_state(
        self, *, viewport: dict[str, Any], scale: str, start: float, end: float
    ) -> dict[str, Any]:
        candidates = self._cover_candidates_from_viewport(viewport)
        preference = None
        if self._cover_store is not None:
            preference = await self._cover_store.get_preference(
                scale=scale,
                period_start=start,
                period_end=end,
            )
        return self._cover_state_from_preference(candidates=candidates, preference=preference)

    @staticmethod
    def _cover_state_from_preference(
        *, candidates: list[dict[str, Any]], preference: dict[str, Any] | None
    ) -> dict[str, Any]:
        if preference is not None:
            mode = str(preference.get("mode") or "")
            if mode == "hidden":
                return {
                    "mode": "hidden",
                    "asset_ref": None,
                    "source": "hidden",
                    "candidates": candidates,
                }
            if mode == "asset":
                asset_ref = str(preference.get("asset_ref") or "").strip() or None
                source = str(preference.get("source") or "current_period")
                if asset_ref:
                    candidate_refs = {str(item.get("asset_ref") or "") for item in candidates}
                    if asset_ref not in candidate_refs:
                        candidates = [
                            {
                                "asset_ref": asset_ref,
                                "source": source,
                                "label": "",
                                "cluster_id": None,
                                "episode_id": None,
                            },
                            *candidates,
                        ]
                return {
                    "mode": "asset",
                    "asset_ref": asset_ref,
                    "source": source,
                    "candidates": candidates,
                }

        auto_asset_ref = candidates[0]["asset_ref"] if candidates else None
        return {
            "mode": "auto",
            "asset_ref": auto_asset_ref,
            "source": "auto",
            "candidates": candidates,
        }

    @staticmethod
    def _cover_candidates_from_viewport(viewport: dict[str, Any]) -> list[dict[str, Any]]:
        clusters = list(viewport.get("clusters") or [])
        ranked = sorted(
            clusters,
            key=lambda cluster: (
                0 if cluster.get("user_pinned") else 1,
                -(float(cluster.get("time_end") or 0.0) - float(cluster.get("time_start") or 0.0)),
            ),
        )
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for cluster in ranked:
            refs: list[str] = []
            representative_ref = str(cluster.get("representative_asset_ref") or "").strip()
            if representative_ref:
                refs.append(representative_ref)
            media_refs = cluster.get("media_refs") or []
            if isinstance(media_refs, list):
                refs.extend(str(ref).strip() for ref in media_refs if str(ref or "").strip())

            label = str(
                cluster.get("slice_narrative")
                or cluster.get("summary")
                or cluster.get("label")
                or ""
            ).strip()
            for ref in refs:
                if ref in seen:
                    continue
                seen.add(ref)
                candidates.append(
                    {
                        "asset_ref": ref,
                        "source": "current_period",
                        "label": label,
                        "cluster_id": str(cluster.get("block_id") or ""),
                        "episode_id": str(cluster.get("episode_id") or "") or None,
                    }
                )
        return candidates

    async def _resolve_photo_library_asset_from_l1(
        self,
        asset_ref: str,
    ) -> tuple[Optional[str], Optional[str]]:
        asset_id = _photo_library_asset_id(asset_ref)
        if not asset_id:
            return None, None
        l1_store = getattr(self._unified_memory, "l1", None)
        if l1_store is None or not hasattr(l1_store, "query_events"):
            return None, None
        try:
            events = await l1_store.query_events(
                source_filters=list(PHOTO_LIBRARY_SOURCE_FILTERS),
                limit=5000,
                order_by="timestamp_desc",
            )
        except Exception:
            return None, None

        for event in events or []:
            metadata = _photo_metadata(event)
            for photo in _iter_representative_photos(metadata) or []:
                candidate = photo.get("asset_local_id") or photo.get("local_identifier")
                if not isinstance(candidate, str) or candidate.strip() != asset_id:
                    continue
                path = photo.get("path")
                if not isinstance(path, str) or not path.strip():
                    return None, None
                content_type = photo.get("mime_type") or photo.get("content_type")
                if not isinstance(content_type, str) or not content_type.strip():
                    content_type = _guess_image_content_type(path)
                return path.strip(), content_type.strip()
        return None, None

    async def get_context_bundle(self, anchor_id: str) -> Optional[dict]:
        if getattr(self._unified_memory, "l1", None) is None:
            return None
        event = await self._unified_memory.l1.get_user_visible_event(anchor_id)
        if event is not None:
            payload = self._event_to_timeline_payload(event)
            anchor = {
                "anchor_id": anchor_id,
                "anchor_type": "event",
                "title": payload["title"],
                "summary": payload["summary"],
                "representative_event_ids": [anchor_id],
            }
            return await self._viewport_builder.build_context_bundle(anchor=anchor)

        if anchor_id.startswith("episode:"):
            episode_id = anchor_id.split(":", 1)[1]
            anchor = {
                "anchor_id": anchor_id,
                "anchor_type": "episode",
                "title": episode_id.replace("_", " ").replace("-", " ").title(),
                "summary": "",
                "episode_id": episode_id,
            }
            return await self._viewport_builder.build_context_bundle(anchor=anchor)

        anchor = {
            "anchor_id": anchor_id,
            "anchor_type": "cluster",
            "title": anchor_id.replace(":", " ").title(),
            "summary": "",
            "representative_event_ids": [],
        }
        return await self._viewport_builder.build_context_bundle(anchor=anchor)

    @staticmethod
    def _event_to_timeline_payload(event: dict) -> dict:
        metadata = TimelineService._event_metadata(event)
        activity_snapshot = activity_snapshot_from_metadata(metadata)
        occurred_at = float(event.get("timestamp") or event.get("created_at") or 0.0)
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(
                activity_snapshot.get("source_type") or event.get("source") or "memory"
            ),
            "source_item_id": str(
                activity_snapshot.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
                or ""
            ),
            "occurred_at": occurred_at,
            "captured_at": float(event.get("created_at") or occurred_at),
            "title": str(
                activity_snapshot.get("title")
                or event.get("event_type")
                or core_i18n.t("timeline.raw_event.memory_title", fallback="Memory Event")
            ),
            "summary": str(activity_snapshot.get("summary") or event.get("content") or ""),
            "retention_mode": str(
                activity_snapshot.get("retention_mode")
                or event.get("retention_class")
                or "compressible"
            ),
            "raw_payload_ref": activity_snapshot.get("raw_payload_ref")
            or metadata.get("raw_payload_ref"),
            "content_blocks": activity_snapshot.get("content_blocks")
            or [{"kind": "text", "value": str(event.get("content") or "")}],
            "entities": activity_snapshot.get("entities") or [],
            "tags": activity_snapshot.get("tags") or [],
            "privacy_labels": activity_snapshot.get("privacy_labels") or [],
            "processing_status": activity_snapshot.get("processing_status") or {},
            "provenance": activity_snapshot.get("provenance") or metadata,
        }

    @staticmethod
    def _event_metadata(event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        metadata_json = event.get("metadata_json")
        if isinstance(metadata_json, dict):
            return metadata_json
        return {}
