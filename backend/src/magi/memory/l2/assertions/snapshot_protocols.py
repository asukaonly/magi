"""Shared snapshot host protocol for L2 assertion snapshot helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

import aiosqlite


class _SnapshotHostProtocol(Protocol):
    db_path: str

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _engagement_value(self, value: str) -> float: ...

    def _is_assertion_expired(self, assertion: Dict[str, Any], *, now: float | None = None) -> bool: ...

    def _build_snapshot_evolution_payload(
        self,
        *,
        existing_snapshot: Dict[str, Any] | None,
        core_traits: Dict[str, Any],
        preferences: Dict[str, Any],
        relationship_topology: Dict[str, Any],
        assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> Dict[str, Any]: ...

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str) -> Optional[Dict[str, Any]]: ...


__all__ = ["_SnapshotHostProtocol"]
