"""Summary evidence link helpers for L3 memory."""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, Callable, Mapping


def row_to_summary_event_link(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "link_id": str(row["link_id"]),
        "summary_id": str(row["summary_id"]),
        "event_id": str(row["event_id"]),
        "link_role": str(row["link_role"]),
        "evidence_weight": float(row["evidence_weight"]),
        "created_at": float(row["created_at"]),
    }


def row_to_summary_task_link(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "link_id": str(row["link_id"]),
        "summary_id": str(row["summary_id"]),
        "task_id": str(row["task_id"]),
        "link_role": str(row["link_role"]),
        "created_at": float(row["created_at"]),
    }


def normalize_event_ids(event_ids: Iterable[Any]) -> list[str]:
    return [str(event_id) for event_id in event_ids if str(event_id).strip()]


def build_summary_event_link_rows(
    *,
    summary_id: str,
    event_ids: Iterable[str],
    created_at: float,
    link_id_factory: Callable[[], str] | None = None,
) -> list[tuple[str, str, str, str, float, float]]:
    make_link_id = link_id_factory or _make_event_link_id
    return [
        (make_link_id(), summary_id, event_id, "primary", 1.0, created_at)
        for event_id in event_ids
    ]


def build_summary_task_link_rows(
    *,
    summary_id: str,
    task_ids: Iterable[str],
    created_at: float,
    link_id_factory: Callable[[], str] | None = None,
) -> list[tuple[str, str, str, str, float]]:
    make_link_id = link_id_factory or _make_task_link_id
    return [
        (make_link_id(), summary_id, task_id, "source_task", created_at)
        for task_id in task_ids
    ]


def _make_event_link_id() -> str:
    return f"sel_{uuid.uuid4().hex}"


def _make_task_link_id() -> str:
    return f"stl_{uuid.uuid4().hex}"
