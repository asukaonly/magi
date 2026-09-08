"""Domain queries for retained shadow conflicts used by notification reads and scans."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES
from .common import L2RetrievalQueryHostProtocol

_AUTHORITATIVE_EXCLUDED = (
    *RETRIEVAL_EXCLUDED_STATUSES,
    "superseded",
    "expired",
    "contradicted",
)
_SLOT_FIELDS = ("entity_id", "entity_type", "trait_name", "target_entity_id")
_ConflictRole = Literal["shadow", "authoritative"]
_Assertion = dict[str, Any]
_Slot = tuple[str, str, str, str]


@dataclass(frozen=True)
class ShadowConflictRef:
    """Stable assertion references retained in one conflict notification."""

    shadow_id: str | None
    authoritative_id: str | None


@dataclass(frozen=True)
class ShadowConflictPair:
    """Visible sides of one conflict; unavailable references remain absent."""

    shadow: _Assertion | None = None
    authoritative: _Assertion | None = None


@dataclass(frozen=True)
class ShadowConflictScan:
    """Maintenance scan counts raw shadows and returns only complete live pairs."""

    shadows_seen: int
    pairs: list[ShadowConflictPair]


class ShadowConflictReader(Protocol):
    """L2 read operations consumed by the conflict notification projection."""

    db_path: str

    async def get_shadow_conflict_pairs(
        self, *, references: Sequence[ShadowConflictRef]
    ) -> list[ShadowConflictPair]: ...

    async def list_shadow_conflicts(
        self, *, entity_id: str, entity_type: str, limit: int = 500
    ) -> ShadowConflictScan: ...


def _slot(assertion: _Assertion) -> _Slot:
    return (
        str(assertion["entity_id"]),
        str(assertion["entity_type"]),
        str(assertion["trait_name"]),
        str(assertion["target_entity_id"]),
    )


def _live_side_clause(role: _ConflictRole, *, now: float) -> tuple[str, list[Any]]:
    """Own notification conflict visibility without changing assertion lifecycle."""
    if role == "shadow":
        status_clause, args = "status = ?", ["shadow"]
    else:
        placeholders = ", ".join("?" for _ in _AUTHORITATIVE_EXCLUDED)
        status_clause, args = f"status NOT IN ({placeholders})", list(_AUTHORITATIVE_EXCLUDED)
    return (
        f"{status_clause} AND COALESCE(authority_ref, '') NOT LIKE 'forget:%' "
        "AND (expires_at IS NULL OR expires_at > ?)",
        [*args, now],
    )


def _pair(shadow: _Assertion | None, authoritative: _Assertion | None) -> ShadowConflictPair:
    if shadow is not None and authoritative is not None and _slot(shadow) != _slot(authoritative):
        return ShadowConflictPair()
    return ShadowConflictPair(shadow=shadow, authoritative=authoritative)


async def _read_live_sides(
    host: L2RetrievalQueryHostProtocol,
    db: aiosqlite.Connection,
    *,
    role: _ConflictRole,
    assertion_ids: Sequence[str],
    now: float,
) -> dict[str, _Assertion]:
    live_clause, live_args = _live_side_clause(role, now=now)
    rows: dict[str, _Assertion] = {}
    unique_ids = sorted(set(assertion_ids))
    for start in range(0, len(unique_ids), 400):
        batch = unique_ids[start : start + 400]
        placeholders = ", ".join("?" for _ in batch)
        async with db.execute(
            f"SELECT * FROM tom_trait_assertions WHERE assertion_id IN ({placeholders}) AND {live_clause}",
            [*batch, *live_args],
        ) as cursor:
            for row in await cursor.fetchall():
                assertion = host._assertion_row_to_dict(row)
                rows[assertion["assertion_id"]] = assertion
    return rows


async def _read_slot_authorities(
    host: L2RetrievalQueryHostProtocol,
    db: aiosqlite.Connection,
    *,
    shadows: Sequence[_Assertion],
    now: float,
) -> dict[_Slot, _Assertion]:
    live_clause, live_args = _live_side_clause("authoritative", now=now)
    authorities: dict[_Slot, _Assertion] = {}
    slots = sorted({_slot(shadow) for shadow in shadows})
    for start in range(0, len(slots), 100):
        batch = slots[start : start + 100]
        placeholders = ", ".join("(?, ?, ?, ?)" for _ in batch)
        async with db.execute(
            "SELECT * FROM tom_trait_assertions "
            f"WHERE ({', '.join(_SLOT_FIELDS)}) IN (VALUES {placeholders}) AND {live_clause} "
            "ORDER BY updated_at DESC",
            [*(value for slot in batch for value in slot), *live_args],
        ) as cursor:
            for row in await cursor.fetchall():
                assertion = host._assertion_row_to_dict(row)
                authorities.setdefault(_slot(assertion), assertion)
    return authorities


class L2StoreShadowConflictQueryMixin:
    """Keep conflict visibility and pairing in the L2 query boundary."""

    async def get_shadow_conflict_pairs(
        self, *, references: Sequence[ShadowConflictRef]
    ) -> list[ShadowConflictPair]:
        """Resolve exact stored references without replacing a missing conflict side."""
        if not references:
            return []
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN")
            shadows = await _read_live_sides(
                host,
                db,
                role="shadow",
                now=now,
                assertion_ids=[ref.shadow_id for ref in references if ref.shadow_id],
            )
            authorities = await _read_live_sides(
                host,
                db,
                role="authoritative",
                now=now,
                assertion_ids=[ref.authoritative_id for ref in references if ref.authoritative_id],
            )
        return [
            _pair(shadows.get(ref.shadow_id or ""), authorities.get(ref.authoritative_id or ""))
            for ref in references
        ]

    async def list_shadow_conflicts(
        self, *, entity_id: str, entity_type: str, limit: int = 500
    ) -> ShadowConflictScan:
        """Select the latest visible authority for each live shadow's existing slot."""
        host = cast(L2RetrievalQueryHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN")
            # This count preserves the maintenance scan metric before visibility filtering.
            async with db.execute(
                "SELECT assertion_id FROM tom_trait_assertions "
                "WHERE status = 'shadow' AND entity_id = ? AND entity_type = ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (entity_id, entity_type, int(limit)),
            ) as cursor:
                shadow_ids = [str(row["assertion_id"]) for row in await cursor.fetchall()]
            shadows = await _read_live_sides(
                host, db, role="shadow", assertion_ids=shadow_ids, now=now
            )
            authorities = await _read_slot_authorities(
                host, db, shadows=list(shadows.values()), now=now
            )
        pairs = [
            _pair(shadows[identity], authorities.get(_slot(shadows[identity])))
            for identity in shadow_ids
            if identity in shadows
        ]
        return ShadowConflictScan(
            shadows_seen=len(shadow_ids),
            pairs=[
                pair for pair in pairs if pair.shadow is not None and pair.authoritative is not None
            ],
        )
