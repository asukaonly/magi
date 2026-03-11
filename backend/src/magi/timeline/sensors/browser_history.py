"""Timeline sensor for browser history records."""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from ..contracts import TimelineContentBlock, TimelineEvent
from .base import TimelineSensorBase


class BrowserHistoryTimelineSensor(TimelineSensorBase):
    sensor_id = "timeline.browser_history"
    display_name = "Browser History"
    source_type = "browser_history"
    polling_mode = "interval"
    default_interval = 30
    update_key_fields = ("url", "visit_time", "visit_count")
    relation_edge_whitelist = ("VIEWED", "VISITED", "CARES_ABOUT", "LIKES")

    def source_item_identity(self, item: dict[str, object]) -> str:
        visit_time = float(item.get("visit_time") or 0.0)
        visit_bucket = int(visit_time // 300)
        return f"{item.get('url', '')}:{visit_bucket}"

    def source_item_version_fingerprint(self, item: dict[str, object]) -> str:
        payload = "|".join(
            [
                str(item.get("title", "")),
                str(item.get("visit_count", "")),
                hashlib.sha1(str(item.get("page_content", "")).encode("utf-8")).hexdigest(),
            ]
        )
        return payload

    async def fetch_item(self, item: dict[str, object]) -> dict[str, object]:
        fetched = dict(item)
        if not self.fetch_page_content:
            fetched.pop("page_content", None)
        return fetched

    async def build_timeline_event(self, item: dict[str, object]) -> TimelineEvent:
        parsed = urlparse(str(item.get("url", "")))
        summary = str(item.get("title") or parsed.netloc or item.get("url") or "Visited page")
        content_blocks = [
            TimelineContentBlock(kind="text", value=str(item.get("url", ""))),
        ]
        if self.fetch_page_content and item.get("page_content"):
            content_blocks.append(TimelineContentBlock(kind="text", value=str(item["page_content"])))
        return self._build_event(
            source_item_id=self.source_item_identity(item),
            title=summary,
            summary=summary,
            occurred_at=float(item.get("visit_time") or 0.0),
            content_blocks=content_blocks,
            tags=["browser_history", parsed.netloc] if parsed.netloc else ["browser_history"],
        )
