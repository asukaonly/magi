"""Normalization helpers for Apple Health timeline ingestion."""
from __future__ import annotations

import datetime
from typing import Any

from .types import HEALTH_DATA_TYPES, HealthDataType


def normalize_daily_aggregate(item: dict[str, Any], sensor: Any) -> dict[str, Any]:
    """Normalize daily health data aggregates into timeline events."""
    data_type = item.get("data_type")
    value = float(item.get("value", 0))

    # Get the health data type configuration
    health_type = HEALTH_DATA_TYPES.get(data_type)
    if not health_type:
        return {}

    # Format the title based on data type
    if data_type == "steps":
        title = f"今日步数 {int(value):,}"
    elif data_type == "distance":
        title = f"今日行走 {value:.1f} 公里"
    elif data_type == "flights":
        title = f"今日爬升 {int(value)} 段楼梯"
    elif data_type == "active_energy":
        title = f"今日消耗 {int(value + 0.5)} 千卡"
    else:
        title = f"今日{health_type.display_name} {value}"

    # Format summary
    if data_type == "active_energy":
        summary_value = int(value + 0.5)
    else:
        summary_value = int(value) if value == int(value) else value
    summary = f"{health_type.display_name}：{summary_value}"
    if health_type.unit:
        summary += f" {health_type.unit}"

    # Get date from item or use today
    date_str = item.get("date")
    if date_str:
        occurred_at = datetime.datetime.fromisoformat(date_str).timestamp()
    else:
        occurred_at = datetime.datetime.now().timestamp()

    # Create source_item_id
    source_item_id = f"health_{data_type}_{date_str or datetime.date.today().isoformat()}"

    return {
        "event_id": f"health_{data_type}_{date_str or datetime.date.today().isoformat()}",
        "source_type": "apple_health",
        "source_item_id": source_item_id,
        "occurred_at": occurred_at,
        "title": title,
        "summary": summary,
        "content_blocks": [
            {
                "kind": "text",
                "value": f"{health_type.display_name}：{value}{health_type.unit or ''}"
            }
        ],
        "tags": ["apple_health", data_type, "daily"],
        "provenance": {
            "sensor_id": sensor.sensor_id,
            "data_type": data_type,
            "value": value,
            "unit": health_type.unit,
            "date": date_str or datetime.date.today().isoformat(),
            "health_display_name": health_type.display_name,
        }
    }


def normalize_sleep_session(item: dict[str, Any], sensor: Any) -> dict[str, Any]:
    """Normalize sleep sessions into timeline events."""
    start_time = float(item.get("start_time", 0))
    end_time = float(item.get("end_time", 0))

    # Calculate duration in hours
    duration_hours = (end_time - start_time) / 3600

    # Format title and summary
    title = f"睡眠 {duration_hours:.1f} 小时"
    summary = f"睡眠时长：{duration_hours:.1f} 小时"

    # Create content blocks with sleep details
    content_blocks = [
        {
            "kind": "text",
            "value": f"开始时间：{datetime.datetime.fromtimestamp(start_time).strftime('%H:%M')}"
        },
        {
            "kind": "text",
            "value": f"结束时间：{datetime.datetime.fromtimestamp(end_time).strftime('%H:%M')}"
        },
        {
            "kind": "text",
            "value": f"睡眠时长：{duration_hours:.1f} 小时"
        }
    ]

    # Format start time for source_item_id
    start_dt = datetime.datetime.fromtimestamp(start_time)
    source_item_id = f"health_sleep_{start_dt.strftime('%Y%m%d%H%M%S')}"

    return {
        "event_id": f"health_sleep_{start_dt.strftime('%Y%m%d%H%M%S')}",
        "source_type": "apple_health",
        "source_item_id": source_item_id,
        "occurred_at": start_time,
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": ["apple_health", "sleep", "session"],
        "provenance": {
            "sensor_id": sensor.sensor_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": duration_hours,
            "health_display_name": "Sleep",
        }
    }


def normalize_workout(item: dict[str, Any], sensor: Any) -> dict[str, Any]:
    """Normalize workout sessions into timeline events."""
    start_time = float(item.get("start_time", 0))
    end_time = float(item.get("end_time", 0))
    workout_type = item.get("workout_type", "")
    distance = float(item.get("distance", 0))
    energy_burned = float(item.get("energy_burned", 0))

    # Map workout types to Chinese
    workout_type_mapping = {
        "HKWorkoutActivityTypeRunning": "跑步",
        "HKWorkoutActivityTypeWalking": "步行",
        "HKWorkoutActivityTypeCycling": "骑行",
        "HKWorkoutActivityTypeSwimming": "游泳",
        "HKWorkoutActivityTypeYoga": "瑜伽",
        "HKWorkoutActivityTypeStrengthTraining": "力量训练",
        "HKWorkoutActivityType": "其他",
    }

    # Get Chinese workout name
    workout_name = workout_type_mapping.get(workout_type, "其他运动")

    # Calculate duration
    duration_minutes = (end_time - start_time) / 60

    # Format title
    title = f"{workout_name} {duration_minutes:.0f} 分钟"

    # Build summary with additional details
    summary_parts = [f"{workout_name}：{duration_minutes:.0f} 分钟"]
    if distance > 0:
        summary_parts.append(f"距离：{distance:.1f} 米")
    if energy_burned > 0:
        summary_parts.append(f"消耗：{int(energy_burned)} 千卡")

    summary = " | ".join(summary_parts)

    # Create content blocks
    content_blocks = [
        {
            "kind": "text",
            "value": f"运动类型：{workout_name}"
        },
        {
            "kind": "text",
            "value": f"开始时间：{datetime.datetime.fromtimestamp(start_time).strftime('%H:%M')}"
        },
        {
            "kind": "text",
            "value": f"结束时间：{datetime.datetime.fromtimestamp(end_time).strftime('%H:%M')}"
        },
        {
            "kind": "text",
            "value": f"时长：{duration_minutes:.0f} 分钟"
        }
    ]

    # Add distance and energy to content blocks if available
    if distance > 0:
        content_blocks.append({
            "kind": "text",
            "value": f"距离：{distance:.1f} 米"
        })
    if energy_burned > 0:
        content_blocks.append({
            "kind": "text",
            "value": f"消耗：{int(energy_burned)} 千卡"
        })

    # Format start time for source_item_id
    start_dt = datetime.datetime.fromtimestamp(start_time)
    source_item_id = f"health_workout_{start_dt.strftime('%Y%m%d%H%M%S')}"

    return {
        "event_id": f"health_workout_{start_dt.strftime('%Y%m%d%H%M%S')}",
        "source_type": "apple_health",
        "source_item_id": source_item_id,
        "occurred_at": start_time,
        "title": title,
        "summary": summary,
        "content_blocks": content_blocks,
        "tags": ["apple_health", "workout", "session"],
        "provenance": {
            "sensor_id": sensor.sensor_id,
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration_minutes,
            "workout_type": workout_type,
            "workout_name": workout_name,
            "distance": distance,
            "energy_burned": energy_burned,
        }
    }


def normalize_heart_rate_sample(item: dict[str, Any], sensor: Any) -> dict[str, Any]:
    """Normalize heart rate samples into timeline events."""
    timestamp = float(item.get("timestamp", 0))
    heart_rate = float(item.get("value", 0))

    # Create title and summary
    title = f"心率 {int(heart_rate)} bpm"
    summary = f"心率测量：{int(heart_rate)} 次/分钟"

    # Format timestamp for source_item_id
    dt = datetime.datetime.fromtimestamp(timestamp)
    source_item_id = f"health_heart_rate_{dt.strftime('%Y%m%d%H%M%S')}"

    return {
        "event_id": f"health_heart_rate_{dt.strftime('%Y%m%d%H%M%S')}",
        "source_type": "apple_health",
        "source_item_id": source_item_id,
        "occurred_at": timestamp,
        "title": title,
        "summary": summary,
        "content_blocks": [
            {
                "kind": "text",
                "value": f"心率：{int(heart_rate)} bpm"
            },
            {
                "kind": "text",
                "value": f"时间：{dt.strftime('%H:%M:%S')}"
            }
        ],
        "tags": ["apple_health", "heart_rate", "sample"],
        "provenance": {
            "sensor_id": sensor.sensor_id,
            "timestamp": timestamp,
            "heart_rate": heart_rate,
            "health_display_name": "Heart Rate",
        }
    }


# Registry of normalizers for each health data type
NORMALIZERS = {
    "steps": normalize_daily_aggregate,
    "distance": normalize_daily_aggregate,
    "flights": normalize_daily_aggregate,
    "active_energy": normalize_daily_aggregate,
    "sleep": normalize_sleep_session,
    "workout": normalize_workout,
    "heart_rate": normalize_heart_rate_sample,
}