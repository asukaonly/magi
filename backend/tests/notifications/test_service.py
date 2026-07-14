import time
from magi.notifications.store import NotificationStore
from magi.notifications.service import NotificationService

def _svc(tmp_path):
    s = NotificationStore(str(tmp_path / "n.db")); s.ensure_schema()
    return NotificationService(store=s), s

def _proposal(category="browser_history"):
    # minimal SuggestionProposal-shaped object
    from types import SimpleNamespace
    plugin = SimpleNamespace(
        plugin_id="edge-history",
        name="Edge History",
        name_i18n={"zh-CN": "Edge 浏览器历史"},
        icon="lucide:globe",
        installed=False,
    )
    plugin.model_dump = lambda: {
        "plugin_id": plugin.plugin_id,
        "name": plugin.name,
        "name_i18n": plugin.name_i18n,
        "icon": plugin.icon,
        "installed": plugin.installed,
    }
    return SimpleNamespace(category=category, dedupe_key=category,
                           plugins=[plugin], confidence=0.9,
                           rationale={"zh": "看浏览器历史", "en": "browser history"})

def test_materialize_inserts_localized(tmp_path):
    svc, store = _svc(tmp_path)
    svc.materialize(user_id="default_user", locale="zh", proposals=[_proposal()])
    items = store.list_for_user("default_user")
    assert len(items) == 1
    assert items[0].title  # non-empty
    assert "浏览" in items[0].body
    import json
    payload = json.loads(items[0].payload_json)
    assert payload["plugins"][0]["name_i18n"]["zh-CN"] == "Edge 浏览器历史"
    assert payload["plugins"][0]["installed"] is False

def test_materialize_dedups_active(tmp_path):
    svc, store = _svc(tmp_path)
    svc.materialize(user_id="default_user", locale="zh", proposals=[_proposal()])
    svc.materialize(user_id="default_user", locale="zh", proposals=[_proposal()])
    assert len(store.list_for_user("default_user")) == 1   # bumped, not duplicated

def test_dismiss_records_preference(tmp_path):
    import magi.notifications.store as store_mod
    s = store_mod.NotificationStore(str(tmp_path / "n.db")); s.ensure_schema()
    nid = s.insert(store_mod.NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="browser_history", title="看看你的浏览器历史", body="b", created_at_ms=1))
    recorded = []
    from magi.notifications.service import NotificationService
    # The recorder receives the row's localized title as the 3rd arg so the
    # restore list can show the same string the user saw.
    svc = NotificationService(store=s,
        record_dismissal=lambda key, kind, title=None: recorded.append((key, kind, title)))
    svc.dismiss(nid, "explicit")
    assert s.get(nid).status == "dismissed"
    assert recorded == [("browser_history", "explicit", "看看你的浏览器历史")]


def test_dismiss_all_records_each_key(tmp_path):
    import magi.notifications.store as store_mod
    s = store_mod.NotificationStore(str(tmp_path / "n.db")); s.ensure_schema()
    s.insert(store_mod.NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="a", title="标题A", body="b", created_at_ms=1))
    s.insert(store_mod.NotificationRow(user_id="default_user", kind="suggestion",
        dedupe_key="b", title="标题B", body="b", created_at_ms=2))
    recorded = []
    from magi.notifications.service import NotificationService
    svc = NotificationService(store=s,
        record_dismissal=lambda key, kind, title=None: recorded.append((key, title)))
    n = svc.dismiss_all("default_user", "explicit")
    assert n == 2
    # Each key is recorded with its own row's localized title.
    assert sorted(recorded) == [("a", "标题A"), ("b", "标题B")]
    assert s.list_for_user("default_user") == []


def test_materialize_reinserts_after_restore(tmp_path):
    # No notification-layer cooldown: a dismissed row does NOT block a fresh
    # insert (suppression is the matcher's job; restore clears that gate).
    import magi.notifications.store as store_mod
    s = store_mod.NotificationStore(str(tmp_path / "n.db")); s.ensure_schema()
    from magi.notifications.service import NotificationService
    svc = NotificationService(store=s)
    from types import SimpleNamespace
    p = SimpleNamespace(category="music", dedupe_key="music", plugins=[],
                        confidence=0.9, rationale={"zh": "x", "en": "y"})
    svc.materialize(user_id="default_user", locale="zh", proposals=[p])
    nid = s.list_for_user("default_user")[0].id
    s.mark_dismissed(nid, "explicit")                      # simulate prior dismiss
    svc.materialize(user_id="default_user", locale="zh", proposals=[p])  # matcher would re-pass after restore
    assert len(s.list_for_user("default_user")) == 1       # a fresh row exists again

async def test_materialize_helper_inserts_and_signals(tmp_path, monkeypatch):
    import magi.notifications.store as store_mod
    s = store_mod.NotificationStore(str(tmp_path / "n.db")); s.ensure_schema()
    monkeypatch.setattr(store_mod, "_STORE", s)
    signals = []
    import magi.notifications.service as svc_mod
    async def fake_signal(**kw): signals.append(kw)
    monkeypatch.setattr(svc_mod, "_emit_notification_added_signal", fake_signal)
    from types import SimpleNamespace
    p = SimpleNamespace(category="browser_history", dedupe_key="browser_history",
        plugins=[], confidence=0.9, rationale={"zh":"x","en":"y"})
    await svc_mod.materialize_suggestion_notifications(user_id="default_user", locale="zh", proposals=[p])
    assert len(s.list_for_user("default_user")) == 1
    assert signals and signals[0]["unread_count"] == 1
