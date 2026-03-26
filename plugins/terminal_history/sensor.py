"""Timeline sensor for Terminal History."""
from __future__ import annotations

import hashlib
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from magi.awareness import SensorBase, ContentBlock, SensorMemoryPolicy, SensorOutput, SensorSyncContext, SensorSyncResult

from .exceptions import ShellNotSupportedError
from .filters import SensitiveCommandFilter
from .normalizers import normalize_terminal_command
from .reader import TerminalHistoryReader
from .types import TerminalCommand


class TerminalHistorySensor(SensorBase):
    """Timeline sensor for Terminal History data."""

    sensor_id = "timeline.terminal_history"
    display_name = "Terminal History"
    source_type = "terminal_history"
    polling_mode = "interval"
    default_interval = 15  # 15 minutes
    update_key_fields = ("command", "executed_at")
    relation_edge_whitelist = ("EXECUTED", "USED")
    supports_pull_sync = True

    memory_policy = SensorMemoryPolicy(
        cognition_eligible=False,
        importance_bias=0.3,
    )

    def __init__(
        self,
        *,
        retention_mode: Optional[str] = None,
        shell: Optional[str] = None,
        history_file: Optional[str] = None,
        reader: Optional[TerminalHistoryReader] = None,
    ):
        super().__init__()
        self.retention_mode = retention_mode or "analyze_only"
        self._shell = shell
        self._history_file = history_file
        self._reader = reader
        self._filter: Optional[SensitiveCommandFilter] = None
        self._last_seen_commands: dict[str, float] = {}  # For dedup tracking

    @property
    def reader(self) -> TerminalHistoryReader:
        """Get or create TerminalHistoryReader instance (lazy initialization)."""
        if self._reader is None:
            if sys.platform != "darwin":
                raise ShellNotSupportedError("Only macOS is supported")
            self._reader = TerminalHistoryReader(
                shell=self._shell,
                history_file=self._history_file,
            )
        return self._reader

    def _get_filter(self, settings: dict[str, Any]) -> SensitiveCommandFilter:
        """Get or create the sensitive command filter."""
        if self._filter is None:
            mode = settings.get("sensitive_mode", "redact")
            additional_keywords = settings.get("sensitive_keywords", [])
            self._filter = SensitiveCommandFilter(
                mode=mode,
                additional_keywords=additional_keywords,
            )
        return self._filter

    def source_item_identity(self, item: dict) -> str:
        """Generate unique identity for a source item."""
        command = item.get("command", "")
        executed_at = item.get("executed_at", 0)
        if isinstance(executed_at, datetime):
            executed_at = executed_at.timestamp()
        return f"terminal_{int(executed_at)}_{abs(hash(command) % 10000):04d}"

    def source_item_version_fingerprint(self, item: dict) -> str:
        """Generate version fingerprint for change detection."""
        version_parts = [
            str(item.get("command", "")),
            str(item.get("executed_at", "")),
        ]
        return hashlib.sha1("|".join(version_parts).encode("utf-8")).hexdigest()

    async def collect_items(self, context: SensorSyncContext) -> SensorSyncResult:
        """Collect terminal history data from history files."""
        sensor_settings = (
            context.plugin_settings.get("sensors", {}).get(self.source_type, {})
            if isinstance(context.plugin_settings.get("sensors", {}), dict)
            else {}
        )

        # Get settings
        lookback_days = int(sensor_settings.get("initial_sync_lookback_days", 7))
        dedup_window_seconds = int(sensor_settings.get("dedup_window_seconds", 60))

        # Determine start timestamp
        if context.last_cursor:
            try:
                last_timestamp = float(context.last_cursor)
                start_timestamp = last_timestamp
            except (ValueError, TypeError):
                start_timestamp = (datetime.now() - timedelta(days=lookback_days)).timestamp()
        else:
            # Initial sync - use lookback period
            initial_policy = sensor_settings.get("initial_sync_policy", "lookback_days")
            if initial_policy == "from_now":
                start_timestamp = datetime.now().timestamp()
            elif initial_policy == "full":
                start_timestamp = None  # Read all history
            else:
                start_timestamp = (datetime.now() - timedelta(days=lookback_days)).timestamp()

        # Read commands from history
        try:
            commands = self.reader.read_commands(
                start_timestamp=start_timestamp,
                limit=context.limit,
            )
        except Exception as e:
            return SensorSyncResult(
                items=[],
                next_cursor=None,
                watermark_ts=time.time(),
                stats={
                    "count": 0,
                    "error": str(e),
                },
            )

        # Get filter
        cmd_filter = self._get_filter(sensor_settings)

        # Process commands
        items = []
        latest_timestamp = context.last_success_at or 0
        seen_in_session: set[str] = set()

        for cmd in commands:
            # Apply sensitive command filter
            processed = cmd_filter.process(cmd.command)
            if processed is None:
                # Command was blocked
                continue

            # Session-based deduplication
            dedup_key = self._make_dedup_key(processed, cmd.executed_at, dedup_window_seconds)
            if dedup_key in seen_in_session:
                continue
            seen_in_session.add(dedup_key)

            # Create item
            item = {
                "command": processed,  # Use potentially redacted version
                "executed_at": cmd.executed_at,
                "shell": cmd.shell,
                "history_line": cmd.history_line,
                "raw_line": cmd.raw_line if processed == cmd.command else f"[REDACTED] {cmd.raw_line}",
            }
            items.append(item)

            # Track latest timestamp
            ts = cmd.executed_at.timestamp()
            if ts > latest_timestamp:
                latest_timestamp = ts

        # Sort items by execution time (most recent first)
        items.sort(key=lambda x: x.get("executed_at", datetime.min), reverse=True)

        # Determine next cursor
        next_cursor = str(latest_timestamp) if latest_timestamp > 0 else None

        return SensorSyncResult(
            items=items,
            next_cursor=next_cursor,
            watermark_ts=latest_timestamp or time.time(),
            stats={
                "count": len(items),
                "shell": self.reader.shell,
                "filtered": len(commands) - len(items),
            },
        )

    def _make_dedup_key(self, command: str, executed_at: datetime, window_seconds: int) -> str:
        """Create a deduplication key for session-based dedup.

        Commands within the same time window are considered the same session.

        Args:
            command: The command string
            executed_at: Execution timestamp
            window_seconds: Time window in seconds

        Returns:
            Deduplication key
        """
        # Round timestamp to window
        ts = int(executed_at.timestamp())
        window = ts // window_seconds
        return f"{window}:{command}"

    async def build_output(self, item: dict) -> SensorOutput:
        """Build a SensorOutput from a terminal command item."""
        # Normalize the item
        normalized_data = normalize_terminal_command(item, self)

        # Parse execution time for occurred_at
        executed_at = item.get("executed_at")
        if isinstance(executed_at, datetime):
            occurred_at = executed_at.timestamp()
        elif isinstance(executed_at, (int, float)):
            occurred_at = float(executed_at)
        else:
            occurred_at = time.time()

        return self._build_output(
            source_item_id=normalized_data["source_item_id"],
            title=normalized_data["title"],
            summary=normalized_data["summary"],
            occurred_at=occurred_at,
            content_blocks=[
                ContentBlock(kind=block["kind"], value=block["value"])
                for block in normalized_data["content_blocks"]
            ],
            tags=normalized_data["tags"],
            provenance={
                "sensor_id": self.sensor_id,
                **normalized_data["provenance"],
            },
            domain_payload={"retention_mode": self.retention_mode},
        )
