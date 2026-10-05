"""Tests for DismissalRepository — read/write/TTL semantics."""

from __future__ import annotations

import pytest

from datetime import datetime, timedelta, timezone

import magi.system_suggestions.dismissals as dmod
from magi.system_suggestions.contracts import DismissalKind, DismissalRecord
from magi.system_suggestions.dismissals import (
    DismissalRepository,
    is_dismissal_active,
)


@pytest.mark.parametrize(
    "case_expected_active,case_age_days",
    [
        pytest.param(True, 3, id="is_dismissal_active_transient_within_7_days"),
        pytest.param(False, 8, id="is_dismissal_active_transient_expired_after_7_days"),
    ],
)
def test_transient_dismissals_expire_after_seven_days(case_expected_active, case_age_days) -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=case_age_days),
        kind=DismissalKind.TRANSIENT,
    )
    assert is_dismissal_active(rec, now=now) is case_expected_active


@pytest.mark.parametrize(
    "expected_active,age_days",
    [
        pytest.param(True, 29, id="is_dismissal_active_explicit_within_30_days"),
        pytest.param(False, 31, id="is_dismissal_active_explicit_expired_after_30_days"),
    ],
)
def test_explicit_dismissal_expires_after_thirty_days(expected_active, age_days) -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=age_days),
        kind=DismissalKind.EXPLICIT,
    )
    assert is_dismissal_active(rec, now=now) is expected_active


def test_is_dismissal_active_never_always_active() -> None:
    now = datetime.now(timezone.utc)
    rec = DismissalRecord(
        dedupe_key="browser_history",
        dismissed_at=now - timedelta(days=3650),
        kind=DismissalKind.NEVER,
    )
    assert is_dismissal_active(rec, now=now) is True


def test_repository_persists_dismissals_and_applies_each_ttl():
    now = datetime.now(timezone.utc)
    store = {}

    def save(records):
        store.clear()
        store.update(records)

    repo = DismissalRepository(load=lambda: dict(store), save=save)
    repo.record(
        dedupe_key="browser_history", kind=DismissalKind.TRANSIENT, now=now - timedelta(days=10)
    )
    repo.record(dedupe_key="calendar", kind=DismissalKind.EXPLICIT, now=now - timedelta(days=10))
    assert set(store) == {"browser_history", "calendar"}
    assert store["browser_history"].kind is DismissalKind.TRANSIENT
    assert store["calendar"].kind is DismissalKind.EXPLICIT
    reloaded = DismissalRepository(load=lambda: dict(store), save=save)
    assert reloaded.is_dismissed("browser_history", now=now) is False
    assert reloaded.is_dismissed("calendar", now=now) is True
    assert reloaded.is_dismissed("unknown", now=now) is False


@pytest.mark.parametrize("title", [None, "看看你的浏览器历史"])
def test_record_list_clear_roundtrip(monkeypatch, title):
    store: dict = {"preferences": {"unrelated": "preserve"}}

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

    dmod.record_dismissal(
        "browser_history", "explicit", **({"title": title} if title is not None else {})
    )
    active = dmod.list_active_dismissals()
    assert [r.dedupe_key for r in active] == ["browser_history"]
    assert active[0].title == title
    assert active[0].kind is DismissalKind.EXPLICIT
    assert store["preferences"]["suggestion_dismissals"]["browser_history"]["title"] == title
    assert dmod.clear_dismissal("browser_history") is True
    assert dmod.list_active_dismissals() == []
    assert dmod.clear_dismissal("browser_history") is False

    assert store["preferences"]["unrelated"] == "preserve"
