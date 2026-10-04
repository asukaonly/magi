import time
from magi.notifications.store import NotificationStore, NotificationRow

def _store(tmp_path):
    s = NotificationStore(str(tmp_path / "nt.db"))
    s.ensure_schema()
    return s

def _row(**kw):
    base = dict(user_id="default_user", kind="suggestion", dedupe_key="browser_history",
               title="t", body="b", payload_json="{}", created_at_ms=int(time.time()*1000))
    base.update(kw)
    return NotificationRow(**base)

def test_bulk_dismiss_changes_only_visible_rows_for_the_requested_owner(tmp_path, monkeypatch):
    monkeypatch.setattr("magi.notifications.store._now_ms", lambda: 10000)
    store = _store(tmp_path)
    ids = {
        status: store.insert(_row(dedupe_key=status, status=status))
        for status in ["unread", "read", "actioned", "dismissed"]
    }
    other = store.insert(_row(user_id="other", dedupe_key="unread"))
    before = {
        name: store.get(nid) for name, nid in ids.items() if name in {"actioned", "dismissed"}
    }
    assert {row.id for row in store.list_for_user("default_user")} == {ids["unread"], ids["read"]}
    assert store.mark_dismissed_all("default_user", "explicit") == 2
    for name in ["unread", "read"]:
        row = store.get(ids[name])
        assert (row.status, row.dismiss_kind, row.dismissed_at_ms) == (
            "dismissed",
            "explicit",
            10000,
        )
    for name, row in before.items():
        assert store.get(ids[name]) == row
    assert store.get(other).status == "unread"
    assert store.list_for_user("default_user") == []
    assert [row.id for row in store.list_for_user("other")] == [other]


def test_insert_and_list_newest_first(tmp_path):
    s = _store(tmp_path)
    a = s.insert(_row(dedupe_key="a", created_at_ms=1000))
    b = s.insert(_row(dedupe_key="b", created_at_ms=2000))
    items = s.list_for_user("default_user")
    assert [i.id for i in items] == [b, a]            # newest first
    assert s.unread_count("default_user") == 2

def test_find_active_by_dedup_ignores_dismissed(tmp_path):
    s = _store(tmp_path)
    nid = s.insert(_row(dedupe_key="x"))
    assert s.find_active_by_dedup("default_user", "suggestion", "x").id == nid
    s.mark_dismissed(nid, "explicit")
    assert s.find_active_by_dedup("default_user", "suggestion", "x") is None
    # latest row (even dismissed) is retrievable for cooldown decisions:
    latest = s.find_latest_by_dedup("default_user", "suggestion", "x")
    assert latest.status == "dismissed" and latest.dismiss_kind == "explicit"

def test_read_and_action_transitions_preserve_exact_rows_and_other_owners(tmp_path, monkeypatch):
    monkeypatch.setattr("magi.notifications.store._now_ms", lambda: 10000)
    store = _store(tmp_path)
    first, second = [store.insert(_row(dedupe_key=key)) for key in ["a", "b"]]
    other = store.insert(_row(user_id="other", dedupe_key="a"))
    assert store.get(999999) is None
    assert store.get(first).dedupe_key == "a"
    store.mark_read([first])
    assert [
        (store.get(nid).status, store.get(nid).read_at_ms) for nid in [first, second, other]
    ] == [("read", 10000), ("unread", None), ("unread", None)]
    assert store.unread_count("default_user") == 1
    store.mark_read_all("default_user")
    assert [store.get(nid).status for nid in [first, second, other]] == ["read", "read", "unread"]
    assert store.unread_count("default_user") == 0
    store.mark_actioned(first)
    reopened = NotificationStore(tmp_path / "nt.db")
    assert reopened.get(first).status == "actioned"
    assert reopened.get(first).actioned_at_ms == 10000
    assert [row.id for row in reopened.list_for_user("default_user")] == [second]
    assert reopened.get(other).status == "unread"


def test_expiration_physically_deletes_old_nonunread_rows_and_preserves_boundary(tmp_path):
    store = _store(tmp_path)
    deleted_ids = [
        store.insert(_row(dedupe_key=status, status=status, created_at_ms=999))
        for status in ["read", "actioned", "dismissed"]
    ]
    survivors = [
        store.insert(_row(dedupe_key="old-unread", created_at_ms=1)),
        store.insert(_row(dedupe_key="at-cutoff", status="read", created_at_ms=1000)),
        store.insert(_row(dedupe_key="new-read", status="read", created_at_ms=1001)),
    ]
    before = [store.get(nid) for nid in survivors]
    assert store.delete_expired_user_notifications(cutoff_ms=1000) == 3
    reopened = NotificationStore(tmp_path / "nt.db")
    assert [reopened.get(nid) for nid in deleted_ids] == [None, None, None]
    assert [reopened.get(nid) for nid in survivors] == before
