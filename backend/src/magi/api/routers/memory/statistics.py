"""Statistics response helpers for the memory API."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any


SQLITE_SIDE_FILE_SUFFIXES = ("", "-wal", "-shm")


def storage_usage_bytes(paths: list[str | None]) -> int:
    total = 0
    seen_paths: set[str] = set()

    for raw_path in paths:
        if not raw_path:
            continue

        for suffix in SQLITE_SIDE_FILE_SUFFIXES:
            path = Path(f"{raw_path}{suffix}")
            path_key = str(path.resolve(strict=False))
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)

            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue

    return total


def build_l0_statistics(l0_store: Any) -> dict[str, Any]:
    if not l0_store:
        return {
            "active_sessions": 0,
            "total_attention_items": 0,
            "active_attention_items": 0,
            "background_attention_items": 0,
            "resolved_attention_items": 0,
            "superseded_attention_items": 0,
        }

    sessions = l0_store._sessions
    now = time.time()
    status_counts = {
        "active": 0,
        "background": 0,
        "resolved": 0,
        "superseded": 0,
    }
    for session_id in sessions:
        for item in l0_store._attention_items.get(session_id, {}).values():
            expires_at = item.get("expires_at")
            if expires_at is not None and float(expires_at) <= now:
                continue
            status = str(item.get("status") or "")
            if status in status_counts:
                status_counts[status] += 1

    return {
        "active_sessions": len([session for session in sessions.values() if session.get("status") == "active"]),
        "total_attention_items": sum(status_counts.values()),
        "active_attention_items": status_counts["active"],
        "background_attention_items": status_counts["background"],
        "resolved_attention_items": status_counts["resolved"],
        "superseded_attention_items": status_counts["superseded"],
        "db_path": l0_store.checkpoint_db_path,
    }


def build_layer_statistics(
    *,
    unified_memory: Any,
    l1_count: int,
    l2_relation_count: int,
    l2_assertion_count: int,
    l3_count: int,
    l4_count: int,
    integration_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "l0": build_l0_statistics(getattr(unified_memory, "l0", None)),
        "l1": {"event_count": l1_count},
        "l2": {
            "relation_count": l2_relation_count,
            "assertion_count": l2_assertion_count,
        },
        "l3": {"summary_count": l3_count},
        "l4": {"skill_count": l4_count},
    }

    if getattr(unified_memory, "l1", None):
        stats["l1"]["db_path"] = unified_memory.l1.db_path
    if getattr(unified_memory, "l2", None):
        stats["l2"]["db_path"] = unified_memory.l2.db_path
    if getattr(unified_memory, "l3", None):
        stats["l3"]["db_path"] = unified_memory.l3.db_path
    if getattr(unified_memory, "l4", None):
        stats["l4"]["db_path"] = unified_memory.l4.db_path
    if integration_stats is not None:
        stats["integration"] = integration_stats

    stats["l4"].setdefault("open_circuit_breakers", 0)
    stats["total_memories"] = l1_count + l2_relation_count + l2_assertion_count + l3_count + l4_count
    stats["disk_usage_bytes"] = storage_usage_bytes([
        stats["l0"].get("db_path"),
        stats["l1"].get("db_path"),
        stats["l2"].get("db_path"),
        stats["l3"].get("db_path"),
        stats["l4"].get("db_path"),
    ])
    stats["attention"] = {
        "pending_assertions": 0,
        "open_circuit_breakers": stats["l4"].get("open_circuit_breakers", 0),
    }

    return stats
