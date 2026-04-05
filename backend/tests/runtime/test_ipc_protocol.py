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
    def test_parse_request(self) -> None:
        line = json.dumps({"id": "abc", "method": "ping", "params": {"foo": 1}})
        msg = parse_inbound(line)
        assert isinstance(msg, IpcRequest)
        assert msg.id == "abc"
        assert msg.method == "ping"
        assert msg.params == {"foo": 1}

    def test_parse_request_no_params(self) -> None:
        line = json.dumps({"id": "abc", "method": "ping"})
        msg = parse_inbound(line)
        assert isinstance(msg, IpcRequest)
        assert msg.params is None

    def test_parse_notify(self) -> None:
        line = json.dumps({"method": "heartbeat", "params": {"ts": 1}})
        msg = parse_inbound(line)
        assert isinstance(msg, IpcNotify)
        assert msg.method == "heartbeat"
        assert msg.params == {"ts": 1}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            parse_inbound("not json")


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
