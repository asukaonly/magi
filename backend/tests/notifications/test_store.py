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

def test_dismiss_all_dismisses_visible_only(tmp_path):
    s = _store(tmp_path)
    s.insert(_row(dedupe_key="a"))
    b = s.insert(_row(dedupe_key="b")); s.mark_read([b])
    c = s.insert(_row(dedupe_key="c")); s.mark_actioned(c)   # already out of feed
    dismissed = s.mark_dismissed_all("default_user", "explicit")
    assert dismissed == 2                                     # a (unread) + b (read)
    assert s.list_for_user("default_user") == []
    latest_a = s.find_latest_by_dedup("default_user", "suggestion", "a")
    assert latest_a.status == "dismissed" and latest_a.dismiss_kind == "explicit"


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

def test_mark_read_and_all(tmp_path):
    s = _store(tmp_path)
    n1 = s.insert(_row(dedupe_key="a")); n2 = s.insert(_row(dedupe_key="b"))
    s.mark_read([n1])
    assert s.unread_count("default_user") == 1
    s.mark_read_all("default_user")
    assert s.unread_count("default_user") == 0

def test_action_drops_from_default_list(tmp_path):
    s = _store(tmp_path)
    nid = s.insert(_row(dedupe_key="a"))
    s.mark_actioned(nid)
    # default list excludes dismissed but KEEPS actioned? spec: actioned drops from feed.
    ids = [i.id for i in s.list_for_user("default_user")]
    assert nid not in ids

def test_delete_expired_keeps_unread(tmp_path):
    s = _store(tmp_path)
    old_unread = s.insert(_row(dedupe_key="u", created_at_ms=1))
    old_read = s.insert(_row(dedupe_key="r", created_at_ms=1)); s.mark_read([old_read])
    deleted = s.delete_expired_user_notifications(cutoff_ms=1000)
    assert deleted == 1                                  # only the read one
    ids = [i.id for i in s.list_for_user("default_user")]
    assert old_unread in ids and old_read not in ids

def test_get_returns_row_or_none(tmp_path):
    s = _store(tmp_path)
    nid = s.insert(_row(dedupe_key="x"))
    got = s.get(nid)
    assert got is not None and got.id == nid and got.dedupe_key == "x"
    assert s.get(999999) is None
