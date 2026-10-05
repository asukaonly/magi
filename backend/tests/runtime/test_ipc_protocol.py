"""Tests for the IPC protocol module."""

from __future__ import annotations

import json
import pytest

from magi.ipc.protocol import (
    IpcError,
    IpcEvent,
    IpcNotify,
    IpcRequest,
    IpcResponse,
    parse_inbound,
)


class TestParseInbound:
    @pytest.mark.parametrize(
        "extra,expected", [({}, None), ({"params": None}, None), ({"params": {"foo": 1}}, {"foo": 1})]
    )
    def test_request_parsing_preserves_identity_and_optional_params(self, extra, expected):
        msg = parse_inbound(json.dumps({"id": "abc", "method": "ping", **extra}))
        assert isinstance(msg, IpcRequest)
        assert (msg.id, msg.method, msg.params) == ("abc", "ping", expected)


    def test_parse_notify(self) -> None:
        line = json.dumps({"method": "heartbeat", "params": {"ts": 1}})
        msg = parse_inbound(line)
        assert isinstance(msg, IpcNotify)
        assert msg.method == "heartbeat"
        assert msg.params == {"ts": 1}

    @pytest.mark.parametrize(
        "line,error",
        [("not json", json.JSONDecodeError), ("{}", KeyError), ('{"id":"missing-method"}', KeyError)],
    )
    def test_inbound_rejects_invalid_json_or_missing_method(self, line, error):
        with pytest.raises(error):
            parse_inbound(line)


class TestResponseSerialization:
    def test_response_line(self) -> None:
        resp = IpcResponse(id="123", result={"status": "pong"})
        parsed = json.loads(resp.to_line())
        assert parsed == {"id": "123", "result": {"status": "pong"}}

    def test_error_line(self) -> None:
        err = IpcError(id="456", code=-1, message="not found")
        parsed = json.loads(err.to_line())
        assert parsed == {"id": "456", "error": {"code": -1, "message": "not found"}}

    def test_event_line(self) -> None:
        evt = IpcEvent(event="task.done", data={"id": "x"})
        parsed = json.loads(evt.to_line())
        assert parsed == {"event": "task.done", "data": {"id": "x"}}
