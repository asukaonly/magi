from __future__ import annotations

from _shared.sensor_event_payloads import make_sensor_event_payload
from magi.timeline.sensor_event_projection import build_timeline_event_dict


def test_build_timeline_event_dict_has_required_keys() -> None:
    payload = make_sensor_event_payload()
    d = build_timeline_event_dict(payload, event_id="evt-1")
    assert d["event_id"] == "evt-1"
    assert d["source_type"] == "external_activity"
    assert d["source_item_id"] == "win-app-foo-1234"
    assert d["title"] == "Used Chrome"
    assert d["summary"] == "Used Chrome on Mac"
