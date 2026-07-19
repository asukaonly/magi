"""Clear-memory response helpers for the memory API."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field


class ClearResultModel(BaseModel):
    """Count returned for one cleared product area."""

    cleared: bool
    count: int


class ClearResultsModel(BaseModel):
    """Every memory and conversation area covered by a full clear."""

    l0: ClearResultModel
    l1: ClearResultModel
    l2: ClearResultModel
    l3: ClearResultModel
    l4: ClearResultModel
    chat_context: ClearResultModel


class ClearMemoryResponseModel(BaseModel):
    """Confirmed full-memory clear with any deferred recovery warnings."""

    success: bool
    results: ClearResultsModel
    warnings: list[str] = Field(default_factory=list)


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
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "success": True,
        "results": {
            "l0": build_clear_result(l0_count),
            "l1": build_clear_result(l1_count),
            "l2": build_clear_result(l2_count),
            "l3": build_clear_result(l3_count),
            "l4": build_clear_result(l4_count),
            "chat_context": build_clear_result(chat_context_count),
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
    return response


__all__ = [
    "ClearMemoryResponseModel",
    "build_clear_memory_response",
    "build_clear_result",
]
