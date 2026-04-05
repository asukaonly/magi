"""NDJSON protocol helpers matching the Rust IPC protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IpcRequest:
    """Inbound request from Rust gateway (has id, expects response)."""

    id: str
    method: str
    params: dict[str, Any] | None = None


@dataclass
class IpcNotify:
    """Inbound notification from Rust gateway (no id, no response)."""

    method: str
    params: dict[str, Any] | None = None


@dataclass
class IpcResponse:
    """Outbound success response."""

    id: str
    result: Any = field(default_factory=dict)

    def to_line(self) -> str:
        return json.dumps({"id": self.id, "result": self.result}, ensure_ascii=False) + "\n"


@dataclass
class IpcError:
    """Outbound error response."""

    id: str
    code: int
    message: str

    def to_line(self) -> str:
        return (
            json.dumps(
                {"id": self.id, "error": {"code": self.code, "message": self.message}},
                ensure_ascii=False,
            )
            + "\n"
        )


@dataclass
class IpcEvent:
    """Outbound unsolicited event (no id)."""

    event: str
    data: Any = field(default_factory=dict)

    def to_line(self) -> str:
        return json.dumps({"event": self.event, "data": self.data}, ensure_ascii=False) + "\n"


def parse_inbound(line: str) -> IpcRequest | IpcNotify:
    """Parse an NDJSON line from the Rust gateway into a request or notify."""
    obj = json.loads(line)
    if "id" in obj:
        return IpcRequest(id=obj["id"], method=obj["method"], params=obj.get("params"))
    return IpcNotify(method=obj["method"], params=obj.get("params"))
