"""Normalization helpers for Git Activity timeline ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .types import GitActivity


def normalize_git_activity(item: dict[str, Any] | GitActivity, sensor: Any) -> dict[str, Any]:
    """Normalize git activity data into timeline event format.

    Args:
        item: Git activity data (dict or GitActivity object)
        sensor: The sensor instance

    Returns:
        Dictionary with normalized event data
    """
    # Handle both dict and GitActivity object inputs
    if isinstance(item, GitActivity):
        activity = item
    else:
        activity = GitActivity(
            repo_path=item.get("repo_path", ""),
            activity_type=item.get("activity_type", "other"),
            old_sha=item.get("old_sha", ""),
            new_sha=item.get("new_sha", ""),
            message=item.get("message", ""),
            author=item.get("author", ""),
            timestamp=item.get("timestamp", datetime.now()),
            raw_line=item.get("raw_line", ""),
        )

    # Build title (use message, truncate if needed)
    title = activity.message[:100] + "..." if len(activity.message) > 100 else activity.message

    # Build summary
    repo_name = activity.repo_path.split("/")[-1] if activity.repo_path else "unknown"
    executed_str = activity.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    summary = f"[{activity.activity_type}] {activity.message[:50]} @ {repo_name}"

    # Build content blocks
    content_blocks = [
        {
            "kind": "text",
            "value": f"操作：{activity.activity_type}"
        },
        {
            "kind": "text",
            "value": f"仓库：{activity.repo_path}"
        },
        {
            "kind": "text",
            "value": f"时间：{executed_str}"
        },
        {
            "kind": "text",
            "value": f"提交：{activity.old_sha[:8]}..{activity.new_sha[:8]}"
        },
    ]

    # Add author if available
    if activity.author:
        content_blocks.append({
            "kind": "text",
            "value": f"作者：{activity.author}"
        })

    # Build tags
    tags = ["git", activity.activity_type, repo_name]

    # Build provenance
    provenance = {
        "sensor_id": sensor.sensor_id,
        "repo_path": activity.repo_path,
        "activity_type": activity.activity_type,
        "old_sha": activity.old_sha,
        "new_sha": activity.new_sha,
        "author": activity.author,
    }

    # Create unique event ID
    event_id = f"git_{activity.new_sha}_{int(activity.timestamp.timestamp())}"

    return {
        "event_id": event_id,
        "source_type": "git_activity",
        "source_item_id": event_id,
        "occurred_at": activity.timestamp.timestamp(),
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": tags,
        "provenance": provenance,
    }
