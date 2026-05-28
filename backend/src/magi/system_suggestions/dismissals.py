"""Dismissal repository — TTL-checked persistence for system suggestions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from magi.system_suggestions.contracts import DismissalKind, DismissalRecord


# TTL by dismissal kind. NEVER is sentinel — always considered active.
_TTL_BY_KIND: dict[DismissalKind, timedelta | None] = {
    DismissalKind.TRANSIENT: timedelta(days=7),
    DismissalKind.EXPLICIT: timedelta(days=30),
    DismissalKind.NEVER: None,  # never expires
}


def is_dismissal_active(rec: DismissalRecord, *, now: datetime | None = None) -> bool:
    """True if the dismissal still applies (within TTL, or NEVER kind)."""
    if rec.kind == DismissalKind.NEVER:
        return True
    ttl = _TTL_BY_KIND.get(rec.kind)
    if ttl is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - rec.dismissed_at) < ttl


LoadFn = Callable[[], dict[str, DismissalRecord]]
SaveFn = Callable[[dict[str, DismissalRecord]], None]


class DismissalRepository:
    """Read/write dismissal records via injected load/save callables.

    The callables abstract over where the records live (preferences file,
    in-memory dict, etc.). Production wires this to read/write
    UserPreferencesModel.suggestion_dismissals.
    """

    def __init__(self, *, load: LoadFn, save: SaveFn) -> None:
        self._load = load
        self._save = save

    def is_dismissed(self, dedupe_key: str, *, now: datetime | None = None) -> bool:
        """Returns True if there is an active (un-expired) dismissal for this key."""
        records = self._load()
        rec = records.get(dedupe_key)
        if rec is None:
            return False
        return is_dismissal_active(rec, now=now)

    def record(
        self,
        *,
        dedupe_key: str,
        kind: DismissalKind,
        now: datetime | None = None,
    ) -> None:
        """Save a new dismissal record (overwrites prior dismissal for same key)."""
        records = self._load()
        records[dedupe_key] = DismissalRecord(
            dedupe_key=dedupe_key,
            dismissed_at=now or datetime.now(timezone.utc),
            kind=kind,
        )
        self._save(records)
