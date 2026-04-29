"""Procedure response helpers for the memory API."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..schemas import ProcedureResponse


def procedure_response_from_skill(item: Mapping[str, Any]) -> ProcedureResponse:
    return ProcedureResponse(
        skill_id=str(item["skill_id"]),
        skill_name=str(item["skill_name"]),
        skill_category=str(item["skill_category"]),
        success_rate=float(item["success_rate"]),
        total_attempts=int(item["total_attempts"]),
        circuit_breaker_state=str(item["circuit_breaker_state"]),
    )


def build_procedure_list_response(
    *,
    items: Sequence[Mapping[str, Any]],
    total: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "items": [procedure_response_from_skill(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
