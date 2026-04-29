"""Clear-memory response helpers for the memory API."""
from __future__ import annotations

from typing import Any


def build_clear_result(count: int) -> dict[str, Any]:
    return {
        "cleared": True,
        "count": int(count),
    }


def build_clear_memory_response(
    *,
    l0_count: int,
    l1_count: int,
    l2_count: int,
    l3_count: int,
    l4_count: int,
    chat_context_count: int,
) -> dict[str, Any]:
    return {
        "success": True,
        "results": {
            "l0": build_clear_result(l0_count),
            "l1": build_clear_result(l1_count),
            "l2": build_clear_result(l2_count),
            "l3": build_clear_result(l3_count),
            "l4": build_clear_result(l4_count),
            "chat_context": build_clear_result(chat_context_count),
        },
    }
