from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass
class JsonRpcError:
    code: int
    message: str
    data: Any = None


@dataclass
class JsonRpcRequest:
    id: int | str
    method: str
    params: dict | list | None = None
    jsonrpc: str = "2.0"


@dataclass
class JsonRpcNotification:
    method: str
    params: dict | list | None = None
    jsonrpc: str = "2.0"


@dataclass
class JsonRpcResponse:
    id: int | str
    result: Any = None
    error: Optional[JsonRpcError] = None
    jsonrpc: str = "2.0"


Message = Union[JsonRpcRequest, JsonRpcNotification, JsonRpcResponse]


def encode_message(msg: Message) -> bytes:
    if isinstance(msg, JsonRpcRequest):
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": msg.id, "method": msg.method}
        if msg.params is not None:
            body["params"] = msg.params
    elif isinstance(msg, JsonRpcNotification):
        body = {"jsonrpc": "2.0", "method": msg.method}
        if msg.params is not None:
            body["params"] = msg.params
    elif isinstance(msg, JsonRpcResponse):
        body = {"jsonrpc": "2.0", "id": msg.id}
        if msg.error is not None:
            err: dict[str, Any] = {"code": msg.error.code, "message": msg.error.message}
            if msg.error.data is not None:
                err["data"] = msg.error.data
            body["error"] = err
        else:
            body["result"] = msg.result
    else:
        raise TypeError(f"unsupported message: {type(msg)!r}")
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if b"\n" in payload:
        raise ValueError("MCP messages must not contain embedded newlines")
    return payload + b"\n"


def parse_message(raw: bytes) -> Message:
    obj = json.loads(raw.decode("utf-8"))
    if "method" in obj and "id" in obj:
        return JsonRpcRequest(
            id=obj["id"], method=obj["method"], params=obj.get("params")
        )
    if "method" in obj:
        return JsonRpcNotification(method=obj["method"], params=obj.get("params"))
    if "id" in obj:
        err = obj.get("error")
        return JsonRpcResponse(
            id=obj["id"],
            result=obj.get("result"),
            error=JsonRpcError(
                code=err["code"], message=err["message"], data=err.get("data")
            )
            if err is not None
            else None,
        )
    raise ValueError("not a JSON-RPC message")


class FrameDecoder:
    """Buffers bytes and yields complete newline-delimited JSON-RPC payloads.

    Per MCP spec: each message is a single line of JSON terminated by `\\n`,
    with no embedded newlines. Blank lines are ignored.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._buf.extend(chunk)

    def next(self) -> bytes | None:
        while True:
            idx = self._buf.find(b"\n")
            if idx == -1:
                return None
            line = bytes(self._buf[:idx])
            del self._buf[: idx + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            if not line.strip():
                continue
            return line
