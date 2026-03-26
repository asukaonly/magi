"""Timeline sensor for Git Activity."""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from magi.awareness import SensorBase, ContentBlock, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .filters import SensitiveMessageFilter
from .normalizers import normalize_git_activity
from .reader import GitReflogReader, is_git_repo
from .types import GitActivity


class GitActivitySensor(SensorBase):
    """Timeline sensor for Git Activity data."""

    sensor_id = "timeline.git_activity"
    display_name = "Git Activity"
    source_type = "git_activity"
    polling_mode = "interval"
    default_interval = 30  # 30 minutes
    update_key_fields = ("new_sha", "timestamp")
    relation_edge_whitelist = ("COMMITTED", "CHECKED_OUT", "MERGED", "REBASED")
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy(
        cognition_eligible=False,
        importance_bias=0.4,
    )

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        repos: Optional[list[str]] = None,
    ):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self._repos = repos or []
        self._readers: dict[str, GitReflogReader] = {}
        self._filter: Optional[SensitiveMessageFilter] = None

    def _get_reader(self, repo_path: str) -> Optional[GitReflogReader]:
        """Get or create a reader for a repository."""
        if repo_path not in self._readers:
            expanded_path = str(Path(repo_path).expanduser().resolve())
            reader = GitReflogReader(expanded_path)
            if reader.is_available():
                self._readers[repo_path] = reader
            else:
                self._readers[repo_path] = None
        return self._readers.get(repo_path)

    def _get_filter(self, settings: dict[str, Any]) -> SensitiveMessageFilter:
        """Get or create the sensitive message filter."""
        if self._filter is None:
            mode = settings.get("sensitive_mode", "redact")
            additional_keywords = settings.get("sensitive_keywords", [])
            self._filter = SensitiveMessageFilter(
                mode=mode,
                additional_keywords=additional_keywords,
            )
        return self._filter

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        repo = item.get("repo_path", "unknown")
        new_sha = item.get("new_sha", "")
        timestamp = item.get("timestamp", 0)
        if isinstance(timestamp, datetime):
            timestamp = int(timestamp.timestamp())
        # Create a unique ID based on repo, sha, and timestamp
        repo_hash = hashlib.md5(repo.encode()).hexdigest()[:8]
        return f"git_{repo_hash}_{new_sha[:8]}_{timestamp}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        version_parts = [
            str(item.get("new_sha", "")),
            str(item.get("message", "")),
            str(item.get("timestamp", "")),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect git activity data from configured repositories."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Get configured repositories
        repos = sensor_settings.get("repos", self._repos)
        if not repos:
            return SensorSyncResult(
                items=[],
                next_cursor=None,
                watermark_ts=time.time(),
                stats={"count": 0, "error": "No repositories configured"},
            )

        # Get settings
        lookback_days = int(sensor_settings.get("initial_sync_lookback_days", 30))

        initial_policy = sensor_settings.get("initial_sync_policy", "lookback_days")

        # Determine start timestamp
        if context.last_cursor:
            try:
                start_timestamp = float(context.last_cursor)
            except (ValueError, TypeError):
                start_timestamp = (datetime.now() - timedelta(days=lookback_days)).timestamp()
        else:
            # Initial sync - use lookback period
            if initial_policy == "from_now":
                start_timestamp = datetime.now().timestamp()
            elif initial_policy == "full":
                start_timestamp = None  # Read all history
            else:
                start_timestamp = (datetime.now() - timedelta(days=lookback_days)).timestamp()

        # Get filter
        msg_filter = self._get_filter(sensor_settings)

        # Collect from all repos
        all_items = []
        latest_timestamp = context.last_success_at or 0
        errors = []

        for repo_path in repos:
            repo_path = str(repo_path).strip()
            if not repo_path:
                continue

            # Validate repo
            if not is_git_repo(repo_path):
                errors.append(f"Invalid repo: {repo_path}")
                continue

            # Get reader
            reader = self._get_reader(repo_path)
            if reader is None:
                errors.append(f"Cannot read repo: {repo_path}")
                continue

            try:
                activities = reader.read_activities(
                    start_timestamp=start_timestamp,
                    limit=context.limit,
                )

                for activity in activities:
                    # Apply sensitive message filter
                    processed = msg_filter.redact(activity.message)
                    if processed is None:
                        continue

                    item = {
                        "repo_path": activity.repo_path,
                        "activity_type": activity.activity_type,
                        "old_sha": activity.old_sha,
                        "new_sha": activity.new_sha,
                        "message": processed,
                        "author": activity.author,
                        "timestamp": activity.timestamp,
                        "raw_line": activity.raw_line if processed == activity.message else f"[REDACTED] {activity.raw_line}",
                    }
                    all_items.append(item)

                    # Track latest timestamp
                    ts = activity.timestamp.timestamp()
                    if ts > latest_timestamp:
                        latest_timestamp = ts

            except Exception as e:
                errors.append(f"Error reading {repo_path}: {e}")

        # Sort items by timestamp (most recent first)
        all_items.sort(key=lambda x: x.get("timestamp", datetime.min), reverse=True)

        # Determine next cursor
        next_cursor = str(latest_timestamp) if latest_timestamp > 0 else None

        return SensorSyncResult(
            items=all_items,
            next_cursor=next_cursor,
            watermark_ts=latest_timestamp or time.time(),
            stats={
                "count": len(all_items),
                "repos_processed": len(repos) - len(errors),
                "errors": errors if errors else None,
            },
        )

    async def build_output(self, item: dict) -> SensorOutput:
        """Build a SensorOutput from a git activity item."""
        # Normalize the item
        normalized_data = normalize_git_activity(item, self)

        # Parse timestamp for occurred_at
        timestamp = item.get("timestamp")
        if isinstance(timestamp, datetime):
            occurred_at = timestamp.timestamp()
        elif isinstance(timestamp, (int, float)):
            occurred_at = float(timestamp)
        else:
            occurred_at = time.time()

        # Build content blocks
        repo_path = item.get("repo_path", "")
        repo_name = Path(repo_path).name if repo_path else "unknown"
        activity_type = item.get("activity_type", "other")

        # Get translated activity type name
        activity_type_name = self.t(
            f"activity_types.{activity_type}",
            fallback=activity_type,
        )

        content_blocks = [
            ContentBlock(kind="text", value=self.t("content_blocks.repo", repo_path=repo_path)),
            ContentBlock(kind="text", value=self.t("content_blocks.operation", operation_type=activity_type_name)),
            ContentBlock(
                kind="text",
                value=self.t(
                    "content_blocks.commit",
                    old_sha=item.get('old_sha', '')[:8],
                    new_sha=item.get('new_sha', '')[:8],
                ),
            ),
        ]

        return self._build_output(
            source_item_id=normalized_data["source_item_id"],
            title=normalized_data["title"],
            summary=normalized_data["summary"],
            occurred_at=occurred_at,
            content_blocks=content_blocks,
            tags=normalized_data["tags"],
            provenance={
                "sensor_id": self.sensor_id,
                **normalized_data["provenance"],
            },
            domain_payload={"retention_mode": self.retention_mode},
        )
