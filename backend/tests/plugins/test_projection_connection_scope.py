"""Only declared, owned connection evidence may reach projection callbacks."""

from types import SimpleNamespace
from unittest.mock import Mock

from magi_plugin_sdk.runtime import PluginConnection
from magi.plugins.projections import PluginProjectionService


def plugin(name="account-a", selectors=None):
    instance = Mock()
    instance.plugin_id = "notes"
    instance.connection = PluginConnection(connection_id=name, plugin_id="notes", display_name=name, enabled=True)
    instance.manifest = SimpleNamespace(plugin_id="notes", projection_sources=["notes"] if selectors is None else selectors, version="0.2.1")
    instance.build_temporal_summary_features.return_value = {"summary_lines": [name]}
    instance.build_recall_artifacts.return_value = {"entity_refs": [{"entity_id": name}]}
    return instance


def event(connection_id="account-a", source="notes", version="v1"):
    return {
        "event_id": connection_id + ":event",
        "source": source,
        "metadata_json": {
            "source_connection_id": connection_id,
            "source_plugin_id": "notes",
            "source_object_version": version,
            "source_evidence_ref": {
                "resource_id": "evidence:" + connection_id,
                "connection_id": connection_id,
                "version": version,
            },
        },
    }


def test_temporal_and_recall_callbacks_receive_only_their_declared_connection():
    first, second, unrelated = plugin(), plugin("account-b"), plugin("intruder", ["notes", "private"])
    service = PluginProjectionService(iter_loaded_plugins=lambda: [first, second, unrelated])
    events = [event(), event("account-b"), event(source="private")]
    features = service.build_temporal_summary_features(events=events, summary_category="notes", period_start=0, period_end=1)
    for instance in (first, second):
        received = instance.build_temporal_summary_features.call_args.kwargs["events"]
        assert len(received) == 1
        assert received[0]["metadata_json"]["source_connection_id"] == instance.connection.connection_id
    unrelated.build_temporal_summary_features.assert_not_called()
    assert set(features) == {"account-a:notes", "account-b:notes"}
    assert features["account-a:notes"]["source_type"] == "notes"
    assert features["account-a:notes"]["summary_lines"] == ["account-a"]
    assert features["account-a:notes"]["projection"]["rule_revision"] == "0.2.1"
    artifacts = service.build_recall_artifacts(events=events, query="notes", query_mode=None)
    assert len(artifacts["entity_refs"]) == 2
    assert artifacts["entity_refs"][0]["projection"]["evidence"][0]["reference"]["version"] == "v1"
    unrelated.build_recall_artifacts.assert_not_called()


def test_missing_selectors_or_mismatched_evidence_fail_closed():
    instance = plugin(selectors=[])
    service = PluginProjectionService(iter_loaded_plugins=lambda: [instance])
    service.build_recall_artifacts(events=[event()], query="q", query_mode=None)
    instance.build_recall_artifacts.assert_not_called()
    instance.manifest.projection_sources = ["notes"]
    forged = event()
    forged["metadata_json"]["source_evidence_ref"]["version"] = "different"
    service.build_recall_artifacts(events=[forged, {"source": "notes"}], query="q", query_mode=None)
    instance.build_recall_artifacts.assert_not_called()


def test_projection_callback_cannot_mutate_shared_host_evidence():
    instance = plugin()
    original = event()

    def mutate(**kwargs):
        kwargs["events"][0]["metadata_json"]["source_connection_id"] = "changed"
        return {"entity_refs": []}

    instance.build_recall_artifacts.side_effect = mutate
    PluginProjectionService(iter_loaded_plugins=lambda: [instance]).build_recall_artifacts(events=[original], query="q", query_mode=None)
    assert original["metadata_json"]["source_connection_id"] == "account-a"
