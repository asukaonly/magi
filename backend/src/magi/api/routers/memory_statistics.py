"""Statistics response helpers for the memory API."""
from __future__ import annotations

from typing import Any


def build_l0_statistics(l0_store: Any) -> dict[str, Any]:
    if not l0_store:
        return {
            "active_sessions": 0,
            "total_goals": 0,
            "total_entities": 0,
            "total_tactics": 0,
        }

    sessions = l0_store._sessions
    return {
        "active_sessions": len([session for session in sessions.values() if session.get("status") == "active"]),
        "total_goals": sum(len(l0_store._goal_stack.get(session_id, [])) for session_id in sessions),
        "total_entities": sum(len(l0_store._active_entities.get(session_id, {})) for session_id in sessions),
        "total_tactics": sum(len(l0_store._temporary_tactics.get(session_id, {})) for session_id in sessions),
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

    return stats
