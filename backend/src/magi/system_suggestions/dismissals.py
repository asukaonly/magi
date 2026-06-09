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


# --- config-backed single source of truth for suggestion dismissals ---
# Seams for tests; default to the live config accessors (imported lazily to
# keep this domain module free of an import-time dependency on magi.config).
def _get_loader():
    from magi.config import get_loader

    return get_loader()


def _save_config(patch: dict) -> None:
    from magi.config import save_config

    save_config(patch)


def load_dismissals_from_config() -> dict[str, DismissalRecord]:
    """Load preferences.suggestion_dismissals as DismissalRecord objects."""
    loader = _get_loader()
    if loader is None:
        return {}
    raw = loader.get_raw_value("preferences", "suggestion_dismissals", default={})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, DismissalRecord] = {}
    for key, value in raw.items():
        if isinstance(value, DismissalRecord):
            out[key] = value
        elif isinstance(value, dict):
            try:
                out[key] = DismissalRecord.model_validate(value)
            except Exception:
                continue
    return out


def record_dismissal(
    dedupe_key: str, kind: str = "explicit", title: str | None = None
) -> None:
    """Write/overwrite a dismissal for dedupe_key via GET→mutate→PUT.

    ``title`` is the localized notification text the user saw; it is stored so
    the restore list can show the same string instead of a humanized key.
    """
    loader = _get_loader()
    if loader is not None:
        loader.load()
    prefs = (loader.get_raw_value("preferences", default={}) if loader else {}) or {}
    if not isinstance(prefs, dict):
        prefs = {}
    dismissals = prefs.get("suggestion_dismissals")
    if not isinstance(dismissals, dict):
        dismissals = {}
    record = DismissalRecord(
        dedupe_key=dedupe_key,
        dismissed_at=datetime.now(timezone.utc),
        kind=DismissalKind(kind),
        title=title,
    )
    dismissals[dedupe_key] = record.model_dump(mode="json")
    prefs["suggestion_dismissals"] = dismissals
    _save_config({"preferences": prefs})


def list_active_dismissals() -> list[DismissalRecord]:
    """Active (non-expired) dismissal records."""
    return [r for r in load_dismissals_from_config().values() if is_dismissal_active(r)]


def clear_dismissal(dedupe_key: str) -> bool:
    """Remove a dismissal. Returns True if one existed."""
    loader = _get_loader()
    if loader is not None:
        loader.load()
    prefs = (loader.get_raw_value("preferences", default={}) if loader else {}) or {}
    if not isinstance(prefs, dict):
        prefs = {}
    dismissals = prefs.get("suggestion_dismissals")
    if not isinstance(dismissals, dict) or dedupe_key not in dismissals:
        return False
    del dismissals[dedupe_key]
    prefs["suggestion_dismissals"] = dismissals
    _save_config({"preferences": prefs})
    return True


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
