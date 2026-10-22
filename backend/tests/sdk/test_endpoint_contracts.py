"""Addresses survive persisted run and plugin transport boundaries."""
import pytest

from magi.agent.run_triggers import build_user_message_trigger
from magi.agent.task_agents.common.contracts import UserMessagePayload
from magi_plugin_sdk.endpoints import EndpointRef, IngressContext
from magi_plugin_sdk.run_trigger import RunTrigger
from magi_plugin_sdk.transport import decode, encode


@pytest.mark.parametrize("field,value", [
    ("connection_id", "account:another"), ("target_id", ""),
    ("contribution_id", "a:b"), ("thread_id", 17), ("device_id", True),
])
def test_endpoint_rejects_ambiguous_identity(field, value):
    values = dict(connection_id="account", contribution_id="telegram", target_id="chat")
    values[field] = value
    with pytest.raises(ValueError):
        EndpointRef(**values)


def test_ingress_survives_fact_run_and_wire_roundtrips():
    origin = EndpointRef("account", "telegram", "chat", "topic")
    ingress = IngressContext("message", "turn-1", origin, origin, channel_clear_generation=4)
    payload = UserMessagePayload.from_dict(
        {"user_id": "u", "session_id": "s", "content": "hello", "turn_id": "turn-1",
         "source": "account:telegram", "metadata": {"ingress": ingress.to_dict()}},
        fallback_user_id="u",
    )
    reloaded = UserMessagePayload.from_dict(payload.to_dict(), fallback_user_id="u")
    trigger = build_user_message_trigger(
        source=reloaded.source, requester=reloaded.user_id, content=reloaded.content,
        turn_id=reloaded.turn_id, ingress=reloaded.ingress,
    )
    assert RunTrigger.from_dict(trigger.to_dict()).ingress == ingress
    assert decode(encode(ingress)) == ingress
    assert origin.registry_key == "account:telegram"


@pytest.mark.parametrize("generation", [-1, True, "4"])
def test_ingress_rejects_invalid_clear_generation(generation):
    endpoint = EndpointRef(None, "chat_sse", "s")
    with pytest.raises(ValueError):
        IngressContext("message", "t", endpoint, endpoint, channel_clear_generation=generation)
