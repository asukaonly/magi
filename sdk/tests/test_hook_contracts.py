"""Public hook values remain JSON-only and independent of the host runtime."""
from dataclasses import replace

import pytest
from pydantic import TypeAdapter, ValidationError

from magi_plugin_sdk.hooks import HookContext, HookDecision, HookEventType, HookOutcome


def test_context_round_trip_retains_typed_event_and_json_values():
    adapter = TypeAdapter(HookContext)
    context = HookContext(event_type=HookEventType.PRE_TOOL_USE, tool_name="read",
                          arguments={"path": "file.txt", "lines": [1, 2]}, extra={"dry_run": True})
    restored = adapter.validate_json(adapter.dump_json(context))
    assert restored == context
    assert restored.event_type is HookEventType.PRE_TOOL_USE
    assert replace(restored, arguments={"path": "another.txt"}).arguments == {"path": "another.txt"}


@pytest.mark.parametrize("payload", [{"service": object()}, {"handler": lambda: None}, {"value": float("inf")}])
def test_context_rejects_non_json_host_objects(payload):
    with pytest.raises(ValidationError):
        HookContext(event_type=HookEventType.PRE_TOOL_USE, extra=payload)


def test_unknown_context_fields_are_rejected():
    with pytest.raises(ValidationError):
        TypeAdapter(HookContext).validate_python({"event_type": "PreToolUse", "host_registry": {}})


@pytest.mark.parametrize("decision", [
    HookDecision.cont(source="plugin:a"), HookDecision.deny("Denied"),
    HookDecision.modify(arguments={"limit": 5}), HookDecision.inject("Use this evidence"),
])
def test_decision_round_trip_retains_outcome(decision):
    adapter = TypeAdapter(HookDecision)
    restored = adapter.validate_json(adapter.dump_json(decision))
    assert restored == decision
    assert isinstance(restored.outcome, HookOutcome)


def test_modified_arguments_reject_host_objects():
    with pytest.raises(ValidationError):
        HookDecision.modify(arguments={"service": object()})
