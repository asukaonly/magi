"""Normalization helpers for Screen Time timeline ingestion."""
from __future__ import annotations

from datetime import date
from typing import Any

from .types import DailyScreenTime, AppUsage


def normalize_daily_screen_time(item: dict[str, Any], sensor: Any) -> dict[str, Any]:
    """Normalize daily screen time data into timeline events.

    Args:
        item: Daily screen time data dict
        sensor: The sensor instance

    Returns:
        Dictionary with normalized event data
    """
    daily_data = DailyScreenTime(
        date=item.get("date"),
        total_duration=item.get("total_duration", 0),
        app_usages=item.get("app_usages", [])
    )

    # Format total duration
    hours = daily_data.total_duration // 3600
    if hours >= 1:
        total_str = f"{hours:.1f} 小时"
    else:
        total_str = f"{daily_data.total_duration // 60:.1f} 分钟"

    # Build title
    title = f"屏幕使用 {total_str}"

    # Build summary with top apps
    top_apps = sorted(
        daily_data.app_usages,
        key=lambda x: x.usage_seconds,
        reverse=True
    )[:3]
    top_app_names = [app.app_name for app in top_apps]
    top_apps_str = ", ".join(top_app_names)
    summary = f"{daily_data.date}: 屏幕使用 {total_str},Top apps: {top_apps_str}"

    # Build content blocks
    content_blocks = [
        {
            "kind": "text",
            "value": f"总时长：{total_str}"
        },
        {
            "kind": "text",
            "value": f"日期：{daily_data.date.isoformat()}"
        },
    ]

    # Add app usage details
    if len(daily_data.app_usages) > 0:
        for app in daily_data.app_usages:
            hours = app.usage_seconds // 3600
            if hours >= 1:
                app_str = f"{hours:.1f} 小时"
            else:
                app_str = f"{app.usage_seconds // 60:.1f} 分钟"
            content_blocks.append({
                "kind": "text",
                "value": f"{app.app_name}: {app_str}"
            })

    # Build tags
    tags = ["screen_time", "daily"]

    # Build provenance
    provenance = {
        "sensor_id": sensor.sensor_id,
        "date": daily_data.date.isoformat(),
        "total_duration": daily_data.total_duration,
        "app_count": len(daily_data.app_usages),
    }

    return {
        "event_id": f"screen_time_{daily_data.date.isoformat()}",
        "source_type": "screen_time",
        "source_item_id": f"screen_time_{daily_data.date.isoformat()}",
        "occurred_at": daily_data.date.timestamp(),
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": tags,
        "provenance": provenance,
    }
