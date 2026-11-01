"""The public event schema validates native projection and production fixtures."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from magi.core.client_events import ProductEvent

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts" / "api"


def test_native_event_and_product_payloads_match_language_independent_contract():
    native = json.loads((CONTRACTS / "frontend-native-notification.json").read_text())
    ProductEvent.model_validate(native)
    fixtures = json.loads((CONTRACTS / "frontend-events-examples.json").read_text())
    for event_type, fixture in [
        ("chat_message_upserted", "upsert"), ("chat_message_hidden", "hidden"),
        ("turn_execution_control", "control"), ("agent_response_chunk", "chunk"),
    ]:
        ProductEvent.model_validate({**native, "event_type": event_type, "data": fixtures[fixture]})
    with pytest.raises(ValidationError):
        ProductEvent.model_validate({**native, "event_type": "runtime.notification"})
    with pytest.raises(ValidationError):
        ProductEvent.model_validate({**native, "event_type": "control.ask.requested", "data": {"session_id": "s", "tool_arguments": {}}})
