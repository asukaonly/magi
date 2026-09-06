"""Finite value projections for protocol-only host facades."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerIngressRecord:
    event_id: int
    source_kind: str
    producer: str
    plugin_target: str
    event_type: str
    occurred_at_ms: int
    payload_json: str
    cursor_key: str | None
    status: str
    claimed_by: str | None
    claimed_at_ms: int | None
    processed_at_ms: int | None
    last_error: str | None
    created_at_ms: int
