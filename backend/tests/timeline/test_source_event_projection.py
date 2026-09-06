from __future__ import annotations

from _shared.source_event_payloads import make_source_event_payload
from magi.timeline.source_event_projection import build_timeline_event_dict


def test_build_timeline_event_dict_has_required_keys() -> None:
    payload = make_source_event_payload()
    d = build_timeline_event_dict(payload, event_id="evt-1")
    assert d["event_id"] == "evt-1"
    assert d["source_type"] == "external_activity"
    assert d["source_item_id"] == "win-app-foo-1234"
    assert d["title"] == "Used Chrome"
    assert d["summary"] == "Used Chrome on Mac"
