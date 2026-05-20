"""Timeline service facade over memory-backed viewport and context bundles."""
from __future__ import annotations

from typing import Any, Optional

from .. import i18n as core_i18n
from .contracts import TimelineEvent
from .insight_pipeline import TimelineInsightPipeline
from .viewport_builder import TimelineViewportBuilder


_WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


def _synthesize_standout_title(time_start: float, time_end: float) -> str:
    """Build a readable fallback title from time + duration metadata.

    Used when an episode has no slice_narrative, user_label, or label.
    Format: "周日 14:00 · 3h" (no source/topic info — that would require
    pulling them from the row, which the caller can add later if needed).
    """
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(time_start, tz=timezone.utc)
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


class TimelineService:
    """Provides timeline-oriented operations over unified memory."""

    def __init__(self, unified_memory) -> None:
        self._unified_memory = unified_memory
        self._insight_pipeline = TimelineInsightPipeline(unified_memory)
        self._viewport_builder = TimelineViewportBuilder(
            l1_store=getattr(unified_memory, "l1", None),
            l2_store=getattr(unified_memory, "l2", None),
            l3_store=getattr(unified_memory, "l3", None),
            l4_store=getattr(unified_memory, "l4", None),
            entity_catalog=getattr(unified_memory, "l2_entity_catalog", None),
            location_resolver=getattr(unified_memory, "location_resolver", None),
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
        return await self._viewport_builder.build_viewport(
            scale=scale,
            start=start,
            end=end,
            query=query,
            timezone=timezone,
            focus=focus,
            locale=locale,
        )

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
        from datetime import datetime, timezone

        store = getattr(self._unified_memory, "l2", None)
        if store is None:
            return []

        rows = await store.list_standout_episodes(
            period_start=period_start, period_end=period_end, limit=limit,
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
            items.append({
                "episode_id": r["episode_id"],
                "scale": "day",
                "start": ts,
                "end": te,
                "title": title,
                # TODO(timeline): "date" is formatted in UTC. For non-UTC users this
                # can disagree with their local day boundary. Plan 2 / a later fix
                # should accept a tz parameter (header or query) and format accordingly.
                # The adjacent daily_mood_aggregate uses day_local_date strings as the
                # established convention for user-visible dates.
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "source": "user" if r.get("user_pinned") else "magi",
                "score": float(r.get("standout_score") or 0.0),
            })
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
        """
        if not asset_ref:
            return None

        scheme, _, _ = asset_ref.partition("://")
        if scheme != "photo-library":
            # Future schemes (chat-attachment://, screen-capture://) plug in here.
            return None

        file_path, content_type = await _resolve_photo_library_asset(asset_ref)
        if not file_path:
            return None

        try:
            with open(file_path, "rb") as fh:
                data = fh.read()
        except OSError:
            return None

        return data, content_type or "application/octet-stream"

    async def get_context_bundle(self, anchor_id: str) -> Optional[dict]:
        if getattr(self._unified_memory, "l1", None) is None:
            return None
        event = await self._unified_memory.l1.get_event(anchor_id)
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
        timeline = metadata.get("timeline", {}) if isinstance(metadata.get("timeline"), dict) else {}
        occurred_at = float(event.get("timestamp") or event.get("created_at") or 0.0)
        return {
            "event_id": str(event["event_id"]),
            "source_type": str(timeline.get("source_type") or event.get("source") or "memory"),
            "source_item_id": str(
                timeline.get("source_item_id")
                or event.get("source_item_id")
                or event.get("idempotency_key")
                or ""
            ),
            "occurred_at": occurred_at,
            "captured_at": float(event.get("created_at") or occurred_at),
            "title": str(timeline.get("title") or event.get("event_type") or core_i18n.t("timeline.raw_event.memory_title", fallback="Memory Event")),
            "summary": str(timeline.get("summary") or event.get("content") or ""),
            "retention_mode": str(timeline.get("retention_mode") or event.get("retention_class") or "compressible"),
            "raw_payload_ref": timeline.get("raw_payload_ref") or metadata.get("raw_payload_ref"),
            "content_blocks": timeline.get("content_blocks") or [{"kind": "text", "value": str(event.get("content") or "")}],
            "entities": timeline.get("entities") or [],
            "tags": timeline.get("tags") or [],
            "privacy_labels": timeline.get("privacy_labels") or [],
            "processing_status": timeline.get("processing_status") or {},
            "provenance": timeline.get("provenance") or metadata,
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
