"""Tests for DismissalRepository — read/write/TTL semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import magi.system_suggestions.dismissals as dmod
from magi.system_suggestions.contracts import DismissalKind, DismissalRecord
from magi.system_suggestions.dismissals import (
    DismissalRepository,
    is_dismissal_active,
)


def test_is_dismissal_active_transient_within_7_days() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=3),
        kind=DismissalKind.TRANSIENT,
    )
    assert is_dismissal_active(rec, now=now) is True


def test_is_dismissal_active_transient_expired_after_7_days() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=8),
        kind=DismissalKind.TRANSIENT,
    )
    assert is_dismissal_active(rec, now=now) is False


def test_is_dismissal_active_explicit_within_30_days() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=29),
        kind=DismissalKind.EXPLICIT,
    )
    assert is_dismissal_active(rec, now=now) is True


def test_is_dismissal_active_explicit_expired_after_30_days() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=31),
        kind=DismissalKind.EXPLICIT,
    )
    assert is_dismissal_active(rec, now=now) is False


def test_is_dismissal_active_never_always_active() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=3650),
        kind=DismissalKind.NEVER,
    )
    assert is_dismissal_active(rec, now=now) is True


def test_repository_record_dismissal_persists() -> None:
    store_dict: dict = {}

    def save_fn(new_value):
        store_dict.clear()
        store_dict.update(new_value)

    repo = DismissalRepository(load=lambda: dict(store_dict), save=save_fn)

    repo.record(dedupe_key="browser_history", kind=DismissalKind.EXPLICIT)
    assert "browser_history" in store_dict
    rec = store_dict["browser_history"]
    assert rec.kind == DismissalKind.EXPLICIT


def test_repository_is_dismissed_uses_TTL() -> None:
    now = datetime.now(timezone.utc)
    expired = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=10),
        kind=DismissalKind.TRANSIENT,  # 7-day TTL → expired
    )
    active = DismissalRecord(
        dedupe_key="calendar",
        dismissed_at=now - timedelta(days=10),
        kind=DismissalKind.EXPLICIT,   # 30-day TTL → still active
    )
    store_dict = {"browser_history": expired, "calendar": active}
    repo = DismissalRepository(load=lambda: store_dict, save=lambda v: None)

    assert repo.is_dismissed("browser_history", now=now) is False
    assert repo.is_dismissed("calendar", now=now) is True
    assert repo.is_dismissed("unknown_key", now=now) is False


def test_record_list_clear_roundtrip(monkeypatch):
    store: dict = {"preferences": {}}

    class FakeLoader:
        def load(self): pass
        def get_raw_value(self, *keys, default=None):
            cur = store
            for k in keys:
                if not isinstance(cur, dict) or k not in cur:
                    return default
                cur = cur[k]
            return cur

    def fake_save(patch):
        store["preferences"].update(patch.get("preferences", {}))

    monkeypatch.setattr(dmod, "_get_loader", lambda: FakeLoader())
    monkeypatch.setattr(dmod, "_save_config", fake_save)

    dmod.record_dismissal("browser_history", "explicit")
    active = dmod.list_active_dismissals()
    assert [r.dedupe_key for r in active] == ["browser_history"]
    assert dmod.clear_dismissal("browser_history") is True
    assert dmod.list_active_dismissals() == []
    assert dmod.clear_dismissal("browser_history") is False


def test_record_dismissal_stores_and_returns_title(monkeypatch):
    """record_dismissal persists the localized title; it round-trips on load."""
    store: dict = {"preferences": {}}

    class FakeLoader:
        def load(self):
            pass

        def get_raw_value(self, *keys, default=None):
            cur = store
            for k in keys:
                if not isinstance(cur, dict) or k not in cur:
                    return default
                cur = cur[k]
            return cur

    def fake_save(patch):
        store["preferences"].update(patch.get("preferences", {}))

    monkeypatch.setattr(dmod, "_get_loader", lambda: FakeLoader())
    monkeypatch.setattr(dmod, "_save_config", fake_save)

    dmod.record_dismissal("browser_history", "explicit", title="看看你的浏览器历史")
    active = dmod.list_active_dismissals()
    assert len(active) == 1
    assert active[0].dedupe_key == "browser_history"
    assert active[0].title == "看看你的浏览器历史"


def test_record_dismissal_title_defaults_to_none(monkeypatch):
    """Omitting title leaves it None (back-compat with pre-title records)."""
    store: dict = {"preferences": {}}

    class FakeLoader:
        def load(self):
            pass

        def get_raw_value(self, *keys, default=None):
            cur = store
            for k in keys:
                if not isinstance(cur, dict) or k not in cur:
                    return default
                cur = cur[k]
            return cur

    def fake_save(patch):
        store["preferences"].update(patch.get("preferences", {}))

    monkeypatch.setattr(dmod, "_get_loader", lambda: FakeLoader())
    monkeypatch.setattr(dmod, "_save_config", fake_save)

    dmod.record_dismissal("calendar", "explicit")
    active = dmod.list_active_dismissals()
    assert active[0].title is None
