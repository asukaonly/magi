"""Timeline sensor for local Chrome history."""
from __future__ import annotations

import hashlib
import time
from typing import Any

from magi.awareness import (
    SensorBase,
    ContentBlock,
    L2BatchPolicy,
    SensorMemoryPolicy,
    SensorOutput,
    SensorOutputMetadata,
    SensorSyncContext,
    SensorSyncResult,
)

from .chrome_reader import ChromeHistoryReader, _default_chrome_root
from .normalizers import build_relation_candidates, normalize_domain, parse_title_entities


class ChromeHistoryTimelineSensor(SensorBase):
    """Pull-sync sensor backed by the local Chrome history SQLite database."""

    sensor_id = "timeline.chrome_history"
    display_name = "Chrome History"
    source_type = "chrome_history"
    polling_mode = "interval"
    default_interval = 30
    update_key_fields = ("visit_id",)
    relation_edge_whitelist = ("VIEWED",)
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy()  # defaults match design
    _catch_up_shard_count = 8

    def __init__(
        self,
        *,
        retention_mode: str | None = None,
        source_path: str | None = None,
        fetch_page_content: bool = False,
        profile: str = "Default",
        lookback_hours: int = 24,
        reader: ChromeHistoryReader | None = None,
    ) -> None:
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self.source_path = source_path
        self.fetch_page_content = fetch_page_content
        self.profile = profile
        self.lookback_hours = lookback_hours
        self._reader = reader or ChromeHistoryReader()

    def source_item_identity(self, item: dict[str, Any]) -> str:
        return str(item.get("source_item_id") or item.get("visit_id") or "")

    def source_item_version_fingerprint(self, item: dict[str, Any]) -> str:
        return "|".join(
            [
                str(item.get("visit_id") or ""),
                str(item.get("title") or ""),
                str(item.get("visit_count") or 0),
            ]
        )

    def l2_batch_policy(self, output: SensorOutput) -> L2BatchPolicy | None:
        profile = str(output.provenance.get("profile") or self.profile or "").strip()
        domain = str(output.provenance.get("domain") or "").strip().lower()
        parts = [self.source_type, profile or "default"]
        if domain:
            parts.append(domain)
        catch_up_owner = None
        if domain:
            shard = self._catch_up_shard_for_domain(domain)
            catch_up_owner = f"{self.source_type}:{profile or 'default'}:catchup:{shard}"
        return L2BatchPolicy(
            owner=":".join(parts),
            catch_up_owner=catch_up_owner,
            max_events=20,
            min_ready_events=8,
            max_wait_seconds=180,
        )

    def _catch_up_shard_for_domain(self, domain: str) -> int:
        digest = hashlib.sha1(domain.strip().lower().encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % self._catch_up_shard_count

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )
        source_path = str(sensor_settings.get("source_path") or self.source_path or _default_chrome_root())
        profile = str(sensor_settings.get("profile") or self.profile or "Default")
        lookback_hours = int(sensor_settings.get("lookback_hours", self.lookback_hours))
        initial_sync_policy = str(sensor_settings.get("initial_sync_policy") or "lookback_days")
        initial_sync_lookback_days = max(1, int(sensor_settings.get("initial_sync_lookback_days", 7)))
        initial_lookback_hours: int | None = max(1, initial_sync_lookback_days) * 24
        if context.last_cursor is None:
            if initial_sync_policy == "full":
                initial_lookback_hours = None
            elif initial_sync_policy == "from_now":
                latest_visit_id = self._reader.get_latest_visit_id(source_path=source_path, profile=profile)
                return SensorSyncResult(
                    items=[],
                    next_cursor=str(latest_visit_id) if latest_visit_id > 0 else None,
                    watermark_ts=context.last_success_at or time.time(),
                    stats={
                        "count": 0,
                        "profile": profile,
                        "raw_count": 0,
                        "initial_sync_policy": initial_sync_policy,
                    },
                )
        items = self._reader.read_visits(
            source_path=source_path,
            profile=profile,
            limit=max(1, context.limit),
            last_cursor=context.last_cursor,
            lookback_hours=max(1, lookback_hours) if context.last_cursor is not None else initial_lookback_hours,
        )
        next_cursor = context.last_cursor
        watermark_ts = context.last_success_at
        if items:
            raw_max_visit_id = max(
                int(item.get("last_visit_id") or item.get("visit_id") or 0)
                for item in items
            )
            next_cursor = str(raw_max_visit_id) if raw_max_visit_id > 0 else context.last_cursor
            watermark_ts = max(float(item.get("visit_time") or 0.0) for item in items)
        return SensorSyncResult(
            items=items,
            next_cursor=str(next_cursor) if next_cursor else None,
            watermark_ts=watermark_ts,
            stats={
                "count": len(items),
                "profile": profile,
                "raw_count": sum(int(item.get("merged_visit_count") or 1) for item in items),
                "initial_sync_policy": initial_sync_policy if context.last_cursor is None else "incremental",
            },
        )

    async def build_output(self, item: dict[str, Any]) -> SensorOutput:
        url = str(item.get("canonical_url") or item.get("url") or "")
        title = str(item.get("title") or item.get("domain") or url or "Visited page")
        domain = str(item.get("domain") or normalize_domain(url))
        merged_visit_count = max(1, int(item.get("merged_visit_count") or 1))
        # Use i18n for summary
        if merged_visit_count == 1:
            summary = self.t("summary.single_visit", title=title)
        else:
            summary = self.t("summary.multiple_visits", title=title, count=merged_visit_count)
        content_blocks = [
            ContentBlock(kind="text", value=url),
        ]
        if title:
            content_blocks.append(ContentBlock(kind="text", value=title))
        if self.fetch_page_content and item.get("page_content"):
            content_blocks.append(ContentBlock(kind="text", value=str(item["page_content"])))
        return self._build_output(
            source_item_id=self.source_item_identity(item),
            title=title,
            summary=summary,
            occurred_at=float(item.get("visit_time") or 0.0),
            content_blocks=content_blocks,
            tags=[tag for tag in ("chrome_history", domain) if tag],
            provenance={
                "sensor_id": self.sensor_id,
                "browser": "chrome",
                "profile": str(item.get("profile") or self.profile),
                "visit_id": str(item.get("visit_id") or ""),
                "first_visit_id": str(item.get("first_visit_id") or item.get("visit_id") or ""),
                "last_visit_id": str(item.get("last_visit_id") or item.get("visit_id") or ""),
                "merged_visit_count": merged_visit_count,
                "domain": domain,
                "from_visit": str(item.get("from_visit") or ""),
                "transition": str(item.get("transition") or ""),
                "canonical_url": url,
            },
            domain_payload={"retention_mode": self.retention_mode},
        )

    async def extract_metadata(self, item: dict[str, Any]) -> SensorOutputMetadata:
        domain = str(item.get("domain") or normalize_domain(str(item.get("url") or "")))
        title = str(item.get("title") or "")
        entity_hints = parse_title_entities(title, domain)
        return SensorOutputMetadata(
            entities=entity_hints,
            tags=[tag for tag in ("chrome_history", domain) if tag],
            relation_candidates=build_relation_candidates(item),
        )
