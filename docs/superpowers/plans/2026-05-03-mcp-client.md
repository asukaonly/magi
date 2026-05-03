# MCP Client Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP (Model Context Protocol) client to Magi so external MCP servers' tools and resources flow into the existing tool registry and chat-attachment surfaces, governed by the existing permission gateway.

**Architecture:** New module `backend/src/magi/mcp/` owns connection lifecycle, JSON-RPC framing, and reconciliation with `ToolRegistry`. Remote tools are wrapped in `MCPToolAdapter(Tool)` and registered with prefix `mcp__<server>__<tool>`. Resources are exposed via a catalog and consumed by the chat `@`-picker as ephemeral attachments. Configuration lives in `~/.magi/config/mcp/<server-id>.toml`, loaded on boot, with lazy connection start.

**Tech Stack:** Python 3.10+, asyncio, pydantic v2, anyio for subprocess; `httpx` (already a dep) for Streamable HTTP; pytest + pytest-asyncio for tests.

**Spec:** `docs/superpowers/specs/2026-05-03-mcp-client-design.md`

---

## Chunk 1: Foundation — protocol types, config models, loader

### Task 1: Pydantic models for MCP config

**Files:**
- Create: `backend/src/magi/mcp/__init__.py` (empty re-export later)
- Create: `backend/src/magi/mcp/config.py`
- Test: `backend/tests/mcp/test_config_models.py`

- [ ] **Step 1: Write failing test for stdio config parsing**

```python
# backend/tests/mcp/test_config_models.py
import pytest
from magi.mcp.config import MCPServerConfig, StdioTransport

def test_stdio_minimum_valid():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "github", "name": "GitHub"},
        "transport": {"kind": "stdio", "command": "npx", "args": ["-y", "x"]},
    })
    assert cfg.server.id == "github"
    assert isinstance(cfg.transport, StdioTransport)
    assert cfg.transport.command == "npx"
    assert cfg.runtime.call_timeout_ms == 60000  # default
    assert cfg.server.enabled is True
    assert cfg.server.autostart is False

def test_http_minimum_valid():
    cfg = MCPServerConfig.model_validate({
        "server": {"id": "remote", "name": "Remote"},
        "transport": {"kind": "http", "url": "https://example.com/mcp"},
    })
    assert cfg.transport.kind == "http"
    assert cfg.transport.url == "https://example.com/mcp"

def test_invalid_id_rejected():
    with pytest.raises(ValueError):
        MCPServerConfig.model_validate({
            "server": {"id": "Bad ID!", "name": "x"},
            "transport": {"kind": "stdio", "command": "x"},
        })

def test_stdio_requires_command():
    with pytest.raises(ValueError):
        MCPServerConfig.model_validate({
            "server": {"id": "x", "name": "x"},
            "transport": {"kind": "stdio"},
        })
```

- [ ] **Step 2: Run test, confirm it fails (module missing)**

`pytest backend/tests/mcp/test_config_models.py -v` — expect ImportError.

- [ ] **Step 3: Implement config models**

```python
# backend/src/magi/mcp/config.py
from __future__ import annotations
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, field_validator

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

class ServerSection(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    autostart: bool = False

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                "server.id must match [a-z0-9][a-z0-9_-]{0,63}"
            )
        return v

class StdioTransport(BaseModel):
    kind: Literal["stdio"] = "stdio"
    command: str = Field(..., min_length=1)
    args: list[str] = Field(default_factory=list)
    cwd: str = ""
    env: dict[str, str] = Field(default_factory=dict)

class HttpTransport(BaseModel):
    kind: Literal["http"] = "http"
    url: str = Field(..., min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)

Transport = Annotated[
    Union[StdioTransport, HttpTransport],
    Field(discriminator="kind"),
]

class RuntimeSection(BaseModel):
    call_timeout_ms: int = 60_000
    init_timeout_ms: int = 15_000
    max_restart_attempts: int = 5

class ToolOverride(BaseModel):
    dangerous: bool | None = None
    risk: Literal["low", "medium", "high", "destructive"] | None = None

class MCPServerConfig(BaseModel):
    server: ServerSection
    transport: Transport
    runtime: RuntimeSection = Field(default_factory=RuntimeSection)
    tool_overrides: dict[str, ToolOverride] = Field(default_factory=dict)
```

Also create empty `backend/src/magi/mcp/__init__.py`.

- [ ] **Step 4: Run tests, confirm pass**

`pytest backend/tests/mcp/test_config_models.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/ backend/tests/mcp/
git commit -m "feat(mcp): add MCP server config models"
```

### Task 2: Config loader (split TOML files)

**Files:**
- Create: `backend/src/magi/mcp/loader.py`
- Test: `backend/tests/mcp/test_loader.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/mcp/test_loader.py
from pathlib import Path
import os
import pytest
from magi.mcp.loader import MCPConfigLoader

def write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)

def test_loads_all_files(tmp_path: Path):
    write(tmp_path / "github.toml", """
[server]
id = "github"
name = "GitHub"
[transport]
kind = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
""")
    write(tmp_path / "fs.toml", """
[server]
id = "fs"
name = "FS"
enabled = false
[transport]
kind = "stdio"
command = "uvx"
""")
    loader = MCPConfigLoader(tmp_path)
    cfgs = loader.load_all()
    assert {c.server.id for c in cfgs} == {"github", "fs"}

def test_id_must_match_filename(tmp_path: Path):
    write(tmp_path / "wrong.toml", """
[server]
id = "different"
name = "x"
[transport]
kind = "stdio"
command = "x"
""")
    loader = MCPConfigLoader(tmp_path)
    with pytest.raises(ValueError, match="filename"):
        loader.load_all()

def test_env_expansion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MAGI_TEST_TOKEN", "secret123")
    write(tmp_path / "github.toml", """
[server]
id = "github"
name = "x"
[transport]
kind = "stdio"
command = "npx"
[transport.env]
GITHUB_TOKEN = "${env:MAGI_TEST_TOKEN}"
""")
    loader = MCPConfigLoader(tmp_path)
    [cfg] = loader.load_all()
    assert cfg.transport.env["GITHUB_TOKEN"] == "secret123"

def test_env_expansion_missing_var(tmp_path: Path):
    write(tmp_path / "x.toml", """
[server]
id = "x"
name = "x"
[transport]
kind = "stdio"
command = "npx"
[transport.env]
TOKEN = "${env:DEFINITELY_NOT_SET_XYZ}"
""")
    loader = MCPConfigLoader(tmp_path)
    [cfg] = loader.load_all()
    assert cfg.transport.env["TOKEN"] == ""
```

- [ ] **Step 2: Run, confirm fail**

`pytest backend/tests/mcp/test_loader.py -v`

- [ ] **Step 3: Implement loader**

```python
# backend/src/magi/mcp/loader.py
from __future__ import annotations
import os
import re
from pathlib import Path
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from .config import MCPServerConfig

_ENV_RE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")

def _expand(value: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)

def _expand_strings(obj):
    if isinstance(obj, str):
        return _expand(obj)
    if isinstance(obj, dict):
        return {k: _expand_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_strings(v) for v in obj]
    return obj

class MCPConfigLoader:
    def __init__(self, root: Path):
        self.root = Path(root)

    def load_all(self) -> list[MCPServerConfig]:
        if not self.root.exists():
            return []
        out: list[MCPServerConfig] = []
        for path in sorted(self.root.glob("*.toml")):
            if path.name == "index.toml":
                continue
            data = tomllib.loads(path.read_text())
            data = _expand_strings(data)
            cfg = MCPServerConfig.model_validate(data)
            stem = path.stem
            if cfg.server.id != stem:
                raise ValueError(
                    f"{path}: server.id={cfg.server.id!r} does not match filename {stem!r}"
                )
            out.append(cfg)
        return out
```

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/loader.py backend/tests/mcp/test_loader.py
git commit -m "feat(mcp): add config loader with env expansion"
```

### Task 3: JSON-RPC + MCP message types

**Files:**
- Create: `backend/src/magi/mcp/protocol.py`
- Test: `backend/tests/mcp/test_protocol.py`

- [ ] **Step 1: Write failing tests for message framing**

```python
# backend/tests/mcp/test_protocol.py
from magi.mcp.protocol import (
    encode_message, FrameDecoder, JsonRpcRequest, JsonRpcResponse,
    JsonRpcError, parse_message,
)

def test_encode_request_has_content_length_header():
    req = JsonRpcRequest(id=1, method="initialize", params={"x": 1})
    raw = encode_message(req)
    assert raw.startswith(b"Content-Length: ")
    assert b"\r\n\r\n" in raw

def test_decoder_reads_full_message():
    dec = FrameDecoder()
    req = JsonRpcRequest(id=1, method="ping", params={})
    raw = encode_message(req)
    dec.feed(raw[:5])
    assert dec.next() is None
    dec.feed(raw[5:])
    out = dec.next()
    assert out is not None
    parsed = parse_message(out)
    assert isinstance(parsed, JsonRpcRequest)
    assert parsed.method == "ping"

def test_decoder_handles_back_to_back_messages():
    dec = FrameDecoder()
    a = encode_message(JsonRpcRequest(id=1, method="a"))
    b = encode_message(JsonRpcRequest(id=2, method="b"))
    dec.feed(a + b)
    m1 = parse_message(dec.next())
    m2 = parse_message(dec.next())
    assert m1.method == "a" and m2.method == "b"
    assert dec.next() is None

def test_parse_error_response():
    raw = b'{"jsonrpc":"2.0","id":3,"error":{"code":-32601,"message":"not found"}}'
    msg = parse_message(raw)
    assert isinstance(msg, JsonRpcResponse)
    assert msg.error == JsonRpcError(code=-32601, message="not found")
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Implement protocol**

```python
# backend/src/magi/mcp/protocol.py
from __future__ import annotations
import json
from dataclasses import dataclass, field
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
        body = {"jsonrpc": "2.0", "id": msg.id, "method": msg.method}
        if msg.params is not None:
            body["params"] = msg.params
    elif isinstance(msg, JsonRpcNotification):
        body = {"jsonrpc": "2.0", "method": msg.method}
        if msg.params is not None:
            body["params"] = msg.params
    elif isinstance(msg, JsonRpcResponse):
        body = {"jsonrpc": "2.0", "id": msg.id}
        if msg.error is not None:
            body["error"] = {"code": msg.error.code, "message": msg.error.message}
            if msg.error.data is not None:
                body["error"]["data"] = msg.error.data
        else:
            body["result"] = msg.result
    else:
        raise TypeError(f"unsupported message: {type(msg)!r}")
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload

def parse_message(raw: bytes) -> Message:
    obj = json.loads(raw.decode("utf-8"))
    if "method" in obj and "id" in obj:
        return JsonRpcRequest(id=obj["id"], method=obj["method"], params=obj.get("params"))
    if "method" in obj:
        return JsonRpcNotification(method=obj["method"], params=obj.get("params"))
    if "id" in obj:
        err = obj.get("error")
        return JsonRpcResponse(
            id=obj["id"],
            result=obj.get("result"),
            error=JsonRpcError(code=err["code"], message=err["message"], data=err.get("data"))
            if err is not None else None,
        )
    raise ValueError("not a JSON-RPC message")

class FrameDecoder:
    """Buffers bytes and yields complete LSP-style framed payloads."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._buf.extend(chunk)

    def next(self) -> bytes | None:
        sep = b"\r\n\r\n"
        idx = self._buf.find(sep)
        if idx == -1:
            return None
        header = bytes(self._buf[:idx]).decode("ascii", errors="replace")
        length = None
        for line in header.split("\r\n"):
            k, _, v = line.partition(":")
            if k.strip().lower() == "content-length":
                length = int(v.strip())
        if length is None:
            raise ValueError("missing Content-Length header")
        end = idx + len(sep) + length
        if len(self._buf) < end:
            return None
        body = bytes(self._buf[idx + len(sep): end])
        del self._buf[:end]
        return body
```

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/protocol.py backend/tests/mcp/test_protocol.py
git commit -m "feat(mcp): add JSON-RPC framing + message types"
```

---

## Chunk 2: Connections — stdio + base API + reconnect

### Task 4: Connection abstract base

**Files:**
- Create: `backend/src/magi/mcp/connection.py`
- Test: `backend/tests/mcp/test_connection_base.py`

- [ ] **Step 1: Write failing tests for request/response correlation**

```python
# backend/tests/mcp/test_connection_base.py
import asyncio
import pytest
from magi.mcp.connection import MCPConnection, ConnectionState
from magi.mcp.protocol import JsonRpcResponse, JsonRpcNotification

class FakeTransport(MCPConnection):
    """In-memory transport for testing the request lock-step."""

    def __init__(self):
        super().__init__()
        self.outbox: list = []

    async def _start_transport(self):
        self.state = ConnectionState.CONNECTED

    async def _stop_transport(self):
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg):
        self.outbox.append(msg)

    async def deliver(self, msg):
        await self._dispatch(msg)


@pytest.mark.asyncio
async def test_request_resolves_on_matching_response():
    t = FakeTransport()
    await t.start()
    task = asyncio.create_task(t.request("ping", None, timeout=1.0))
    await asyncio.sleep(0)
    sent = t.outbox[0]
    await t.deliver(JsonRpcResponse(id=sent.id, result={"ok": True}))
    res = await task
    assert res == {"ok": True}

@pytest.mark.asyncio
async def test_request_times_out():
    t = FakeTransport()
    await t.start()
    with pytest.raises(asyncio.TimeoutError):
        await t.request("slow", None, timeout=0.05)

@pytest.mark.asyncio
async def test_notifications_dispatched_to_handlers():
    t = FakeTransport()
    seen = []
    t.on_notification("notifications/x", lambda p: seen.append(p))
    await t.start()
    await t.deliver(JsonRpcNotification(method="notifications/x", params={"v": 1}))
    assert seen == [{"v": 1}]
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Implement base class**

```python
# backend/src/magi/mcp/connection.py
from __future__ import annotations
import asyncio
import enum
import itertools
import logging
from typing import Any, Callable
from .protocol import (
    JsonRpcNotification, JsonRpcRequest, JsonRpcResponse, Message,
)

logger = logging.getLogger(__name__)

class ConnectionState(str, enum.Enum):
    INIT = "init"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class MCPConnection:
    def __init__(self) -> None:
        self.state = ConnectionState.INIT
        self._id_seq = itertools.count(1)
        self._pending: dict[int | str, asyncio.Future] = {}
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}

    # --- public API ---

    async def start(self) -> None:
        self.state = ConnectionState.CONNECTING
        await self._start_transport()

    async def stop(self) -> None:
        await self._stop_transport()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("connection closed"))
        self._pending.clear()

    async def request(self, method: str, params: Any, *, timeout: float) -> Any:
        rid = next(self._id_seq)
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        await self._send_raw(JsonRpcRequest(id=rid, method=method, params=params))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

    async def notify(self, method: str, params: Any = None) -> None:
        await self._send_raw(JsonRpcNotification(method=method, params=params))

    def on_notification(self, method: str, handler: Callable[[Any], None]) -> None:
        self._handlers.setdefault(method, []).append(handler)

    # --- subclass hooks ---

    async def _start_transport(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _stop_transport(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def _send_raw(self, msg: Message) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    # --- internal dispatch ---

    async def _dispatch(self, msg: Message) -> None:
        if isinstance(msg, JsonRpcResponse):
            fut = self._pending.get(msg.id)
            if fut is None:
                logger.warning("MCP response for unknown id=%s", msg.id)
                return
            if msg.error is not None:
                fut.set_exception(RuntimeError(f"MCP error {msg.error.code}: {msg.error.message}"))
            else:
                fut.set_result(msg.result)
        elif isinstance(msg, JsonRpcNotification):
            for h in self._handlers.get(msg.method, []):
                try:
                    h(msg.params)
                except Exception:
                    logger.exception("notification handler error: method=%s", msg.method)
        else:
            logger.warning("server-initiated request not supported yet: %s", msg.method)
```

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/connection.py backend/tests/mcp/test_connection_base.py
git commit -m "feat(mcp): connection base with request/notification dispatch"
```

### Task 5: Stdio connection

**Files:**
- Modify: `backend/src/magi/mcp/connection.py` (append `StdioConnection`)
- Test: `backend/tests/mcp/test_stdio_connection.py`

- [ ] **Step 1: Write failing test using a Python script as fake server**

```python
# backend/tests/mcp/test_stdio_connection.py
import asyncio, sys, textwrap
from pathlib import Path
import pytest
from magi.mcp.connection import StdioConnection
from magi.mcp.config import StdioTransport

FAKE_SERVER = r"""
import sys, json
def write(obj):
    body = json.dumps(obj).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body))
    sys.stdout.buffer.write(body); sys.stdout.buffer.flush()
def read():
    hdrs = b""
    while b"\r\n\r\n" not in hdrs:
        c = sys.stdin.buffer.read(1)
        if not c: return None
        hdrs += c
    h, _, rest = hdrs.partition(b"\r\n\r\n")
    n = int([l.split(b":")[1].strip() for l in h.split(b"\r\n") if l.lower().startswith(b"content-length")][0])
    body = rest + sys.stdin.buffer.read(n - len(rest))
    return json.loads(body)
while True:
    msg = read()
    if msg is None: break
    if msg.get("method") == "echo":
        write({"jsonrpc":"2.0","id":msg["id"],"result":msg["params"]})
    elif msg.get("method") == "boom":
        write({"jsonrpc":"2.0","id":msg["id"],"error":{"code":-1,"message":"boom"}})
"""

@pytest.fixture
def fake_server_script(tmp_path: Path) -> Path:
    p = tmp_path / "fake.py"
    p.write_text(FAKE_SERVER)
    return p

@pytest.mark.asyncio
async def test_stdio_round_trip(fake_server_script: Path):
    transport = StdioTransport(command=sys.executable, args=[str(fake_server_script)])
    conn = StdioConnection(transport)
    await conn.start()
    try:
        result = await conn.request("echo", {"hello": "world"}, timeout=3.0)
        assert result == {"hello": "world"}
    finally:
        await conn.stop()

@pytest.mark.asyncio
async def test_stdio_error_response(fake_server_script: Path):
    transport = StdioTransport(command=sys.executable, args=[str(fake_server_script)])
    conn = StdioConnection(transport)
    await conn.start()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            await conn.request("boom", None, timeout=3.0)
    finally:
        await conn.stop()
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Append `StdioConnection` to `backend/src/magi/mcp/connection.py`**

```python
import os
import asyncio
from .config import StdioTransport
from .protocol import FrameDecoder, encode_message, parse_message

class StdioConnection(MCPConnection):
    def __init__(self, transport: StdioTransport):
        super().__init__()
        self._t = transport
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_buf: list[str] = []

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_buf[-500:])

    async def _start_transport(self) -> None:
        env = {**os.environ, **self._t.env}
        self._proc = await asyncio.create_subprocess_exec(
            self._t.command, *self._t.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._t.cwd or None,
            env=env,
        )
        self.state = ConnectionState.CONNECTED
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())

    async def _stop_transport(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
        finally:
            for t in (self._reader_task, self._stderr_task):
                if t is not None:
                    t.cancel()
            self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise ConnectionError("stdio not started")
        self._proc.stdin.write(encode_message(msg))
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        decoder = FrameDecoder()
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                decoder.feed(chunk)
                while True:
                    raw = decoder.next()
                    if raw is None:
                        break
                    try:
                        msg = parse_message(raw)
                    except Exception:
                        logger.exception("invalid MCP message frame")
                        continue
                    await self._dispatch(msg)
        except asyncio.CancelledError:
            return
        finally:
            self.state = ConnectionState.DISCONNECTED

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                self._stderr_buf.append(line.decode("utf-8", errors="replace").rstrip())
                if len(self._stderr_buf) > 1000:
                    self._stderr_buf = self._stderr_buf[-500:]
        except asyncio.CancelledError:
            return
```

- [ ] **Step 4: Run tests, confirm pass**

`pytest backend/tests/mcp/test_stdio_connection.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/connection.py backend/tests/mcp/test_stdio_connection.py
git commit -m "feat(mcp): stdio transport"
```

### Task 6: HTTP (Streamable) connection

**Files:**
- Modify: `backend/src/magi/mcp/connection.py` (append `HttpConnection`)
- Test: `backend/tests/mcp/test_http_connection.py`

- [ ] **Step 1: Write failing test against an in-process FastAPI fake**

```python
# backend/tests/mcp/test_http_connection.py
import asyncio, json
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
from threading import Thread
from magi.mcp.connection import HttpConnection
from magi.mcp.config import HttpTransport

@pytest.fixture
def http_server():
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(req: Request):
        body = await req.json()
        if body.get("method") == "echo":
            return JSONResponse({"jsonrpc":"2.0","id":body["id"],"result":body["params"]})
        return JSONResponse({"jsonrpc":"2.0","id":body["id"],"error":{"code":-1,"message":"x"}})

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        import time; time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=2)

@pytest.mark.asyncio
async def test_http_round_trip(http_server):
    conn = HttpConnection(HttpTransport(url=http_server))
    await conn.start()
    try:
        result = await conn.request("echo", {"x": 1}, timeout=3.0)
        assert result == {"x": 1}
    finally:
        await conn.stop()
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Implement `HttpConnection`**

Append to `connection.py`:

```python
import httpx
from .config import HttpTransport
from .protocol import JsonRpcRequest

class HttpConnection(MCPConnection):
    """Streamable HTTP transport. POST for requests; SSE for server notifications.

    Notifications are best-effort: if the server does not provide an SSE stream
    we keep working in request/response only mode.
    """

    def __init__(self, transport: HttpTransport):
        super().__init__()
        self._t = transport
        self._client: httpx.AsyncClient | None = None
        self._sse_task: asyncio.Task | None = None

    async def _start_transport(self) -> None:
        self._client = httpx.AsyncClient(headers=self._t.headers, timeout=None)
        self.state = ConnectionState.CONNECTED
        self._sse_task = asyncio.create_task(self._sse_loop())

    async def _stop_transport(self) -> None:
        if self._sse_task is not None:
            self._sse_task.cancel()
        if self._client is not None:
            await self._client.aclose()
        self.state = ConnectionState.DISCONNECTED

    async def _send_raw(self, msg) -> None:
        if not isinstance(msg, JsonRpcRequest):
            # Notifications over HTTP are sent as POST with no expected body
            assert self._client is not None
            body = json.loads(encode_message(msg).split(b"\r\n\r\n", 1)[1])
            await self._client.post(self._t.url, json=body)
            return
        assert self._client is not None
        body = json.loads(encode_message(msg).split(b"\r\n\r\n", 1)[1])
        resp = await self._client.post(self._t.url, json=body)
        resp.raise_for_status()
        # Server may answer inline (JSON) or via SSE; inline is the common case.
        if resp.headers.get("content-type", "").startswith("application/json"):
            await self._dispatch(parse_message(resp.content))

    async def _sse_loop(self) -> None:
        assert self._client is not None
        try:
            async with self._client.stream("GET", self._t.url, headers={"Accept": "text/event-stream"}) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip().encode()
                    try:
                        await self._dispatch(parse_message(payload))
                    except Exception:
                        logger.exception("bad SSE event")
        except (asyncio.CancelledError, httpx.HTTPError):
            return
```

Note: also `import json` at top of `connection.py` if not already imported.

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/connection.py backend/tests/mcp/test_http_connection.py
git commit -m "feat(mcp): streamable http transport"
```

---

## Chunk 3: Tool adapter + manager + tool registry integration

### Task 7: MCP tool adapter

**Files:**
- Create: `backend/src/magi/mcp/tool_adapter.py`
- Test: `backend/tests/mcp/test_tool_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/mcp/test_tool_adapter.py
import pytest
from magi.mcp.tool_adapter import build_adapter_class
from magi_plugin_sdk.tools import ParameterType

REMOTE_TOOL = {
    "name": "create_issue",
    "description": "Create a GitHub issue",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title"],
    },
    "annotations": {"destructiveHint": True},
}

class FakeManager:
    last_call = None

    async def call_remote(self, server_id, tool_name, args, timeout_ms):
        FakeManager.last_call = (server_id, tool_name, args, timeout_ms)
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

@pytest.mark.asyncio
async def test_schema_translation_and_call():
    cls = build_adapter_class(
        server_id="github",
        remote=REMOTE_TOOL,
        manager=FakeManager(),
        call_timeout_ms=30000,
        override=None,
    )
    inst = cls()
    schema = inst.get_schema()
    assert schema.name == "mcp__github__create_issue"
    assert schema.dangerous is True
    names = {p.name for p in schema.parameters}
    assert names == {"title", "body", "labels"}
    title = next(p for p in schema.parameters if p.name == "title")
    assert title.required is True and title.type == ParameterType.STRING
    labels = next(p for p in schema.parameters if p.name == "labels")
    assert labels.type == ParameterType.ARRAY
    assert labels.array_item_type == ParameterType.STRING

    result = await inst.execute({"title": "Bug"}, context=None)
    assert result.success is True
    assert FakeManager.last_call == ("github", "create_issue", {"title": "Bug"}, 30000)

def test_default_dangerous_when_no_annotation():
    remote = {"name": "x", "description": "d", "inputSchema": {"type": "object", "properties": {}}}
    cls = build_adapter_class("s", remote, manager=None, call_timeout_ms=1000, override=None)
    assert cls().get_schema().dangerous is True

def test_readonly_hint_makes_safe():
    remote = {"name": "x", "description": "d", "inputSchema": {"type":"object","properties":{}},
              "annotations": {"readOnlyHint": True}}
    cls = build_adapter_class("s", remote, manager=None, call_timeout_ms=1000, override=None)
    assert cls().get_schema().dangerous is False
```

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Implement adapter**

```python
# backend/src/magi/mcp/tool_adapter.py
from __future__ import annotations
from typing import Any, Optional, Protocol
from magi_plugin_sdk.tools import (
    ParameterType, Tool, ToolErrorCode, ToolParameter, ToolResult, ToolSchema,
)

class _ManagerProto(Protocol):
    async def call_remote(self, server_id: str, tool_name: str, args: dict, timeout_ms: int) -> Any: ...

_TYPE_MAP = {
    "string": ParameterType.STRING,
    "integer": ParameterType.INTEGER,
    "number": ParameterType.FLOAT,
    "boolean": ParameterType.BOOLEAN,
    "array": ParameterType.ARRAY,
    "object": ParameterType.OBJECT,
}

def _translate_params(input_schema: dict | None) -> list[ToolParameter]:
    if not input_schema or input_schema.get("type") != "object":
        return []
    props = input_schema.get("properties") or {}
    required = set(input_schema.get("required") or [])
    out: list[ToolParameter] = []
    for name, sub in props.items():
        ptype = _TYPE_MAP.get(sub.get("type", "string"), ParameterType.STRING)
        item_type = None
        if ptype == ParameterType.ARRAY:
            it = (sub.get("items") or {}).get("type", "string")
            item_type = _TYPE_MAP.get(it, ParameterType.STRING)
        out.append(ToolParameter(
            name=name,
            type=ptype,
            description=sub.get("description", ""),
            required=name in required,
            array_item_type=item_type,
        ))
    return out

def _infer_dangerous(annotations: dict | None, override) -> bool:
    if override is not None and override.dangerous is not None:
        return bool(override.dangerous)
    if not annotations:
        return True  # conservative default
    if annotations.get("readOnlyHint") is True:
        return False
    if annotations.get("destructiveHint") is True:
        return True
    if annotations.get("destructiveHint") is False:
        return False
    return True

def build_adapter_class(
    server_id: str,
    remote: dict,
    manager: _ManagerProto | None,
    call_timeout_ms: int,
    override,
) -> type[Tool]:
    qualified_name = f"mcp__{server_id}__{remote['name']}"
    description = remote.get("description") or ""
    annotations = remote.get("annotations") or {}
    parameters = _translate_params(remote.get("inputSchema"))
    dangerous = _infer_dangerous(annotations, override)

    schema = ToolSchema(
        name=qualified_name,
        description=description,
        parameters=parameters,
        dangerous=dangerous,
    )

    class _Adapter(Tool):
        def __init__(self) -> None:
            super().__init__()
            self.schema = schema

        def get_schema(self) -> ToolSchema:
            return schema

        async def execute(self, parameters: dict, context: Any = None) -> ToolResult:
            try:
                result = await manager.call_remote(  # type: ignore[union-attr]
                    server_id, remote["name"], parameters or {}, call_timeout_ms,
                )
            except Exception as exc:
                return ToolResult(
                    success=False,
                    error=str(exc),
                    error_code=ToolErrorCode.EXECUTION_ERROR,
                )
            if isinstance(result, dict) and result.get("isError"):
                return ToolResult(
                    success=False,
                    error=_extract_text(result),
                    error_code=ToolErrorCode.EXECUTION_ERROR,
                )
            return ToolResult(success=True, output=_extract_text(result), data=result)

    _Adapter.__name__ = f"MCPAdapter_{server_id}_{remote['name']}"
    return _Adapter

def _extract_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)
    parts = result.get("content") or []
    out: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text":
            out.append(p.get("text", ""))
    return "\n".join(out) if out else ""
```

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/mcp/tool_adapter.py backend/tests/mcp/test_tool_adapter.py
git commit -m "feat(mcp): tool adapter wrapping remote tools as Magi Tool"
```

### Task 8: MCPManager — handshake, list, register

**Files:**
- Create: `backend/src/magi/mcp/manager.py`
- Test: `backend/tests/mcp/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/mcp/test_manager.py
import asyncio
import pytest
from magi.mcp.manager import MCPManager
from magi.mcp.config import MCPServerConfig
from magi.tools.registry import ToolRegistry

class StubConnection:
    def __init__(self, tools, resources=None):
        self._tools = tools
        self._resources = resources or []
        self.started = False
        self._handlers = {}

    async def start(self): self.started = True
    async def stop(self): self.started = False
    def on_notification(self, *a, **kw): pass

    async def request(self, method, params, *, timeout):
        if method == "initialize":
            return {"protocolVersion": "2024-11-05", "capabilities": {}}
        if method == "tools/list":
            return {"tools": self._tools}
        if method == "resources/list":
            return {"resources": self._resources}
        if method == "tools/call":
            return {"content": [{"type": "text", "text": f"ran {params['name']}"}], "isError": False}
        raise RuntimeError(f"unexpected {method}")

CFG = MCPServerConfig.model_validate({
    "server": {"id": "demo", "name": "Demo", "autostart": True},
    "transport": {"kind": "stdio", "command": "x"},
})

@pytest.mark.asyncio
async def test_manager_registers_tools():
    registry = ToolRegistry()
    conn = StubConnection(tools=[
        {"name": "echo", "description": "e", "inputSchema": {"type": "object", "properties": {"x":{"type":"string"}}}},
    ])
    mgr = MCPManager(registry=registry, connection_factory=lambda c: conn)
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    names = registry.list_tool_names()
    assert "mcp__demo__echo" in names
    result = await registry.execute_tool("mcp__demo__echo", {"x": "hi"}, context=None)
    assert result.success is True

@pytest.mark.asyncio
async def test_manager_unregisters_on_stop():
    registry = ToolRegistry()
    conn = StubConnection(tools=[{"name":"a","description":"","inputSchema":{"type":"object","properties":{}}}])
    mgr = MCPManager(registry=registry, connection_factory=lambda c: conn)
    mgr.add_config(CFG)
    await mgr.start_server("demo")
    assert "mcp__demo__a" in registry.list_tool_names()
    await mgr.stop_server("demo")
    assert "mcp__demo__a" not in registry.list_tool_names()
```

(If `ToolRegistry` does not have `list_tool_names` or `execute_tool` exactly, adjust to whatever lookup/execution methods the existing mixins expose — refer to `backend/src/magi/tools/registry_lookup.py` and `registry_execution.py`. **Before implementing, read those files** to use the real method names.)

- [ ] **Step 2: Read existing registry methods to align test names**

```bash
sed -n '1,80p' backend/src/magi/tools/registry_lookup.py
sed -n '1,80p' backend/src/magi/tools/registry_execution.py
```

Patch the test to use the actual method names.

- [ ] **Step 3: Confirm fail**

- [ ] **Step 4: Implement manager**

```python
# backend/src/magi/mcp/manager.py
from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable
from .config import MCPServerConfig, StdioTransport, HttpTransport
from .connection import MCPConnection, StdioConnection, HttpConnection
from .tool_adapter import build_adapter_class

logger = logging.getLogger(__name__)

def _default_factory(cfg: MCPServerConfig) -> MCPConnection:
    if isinstance(cfg.transport, StdioTransport):
        return StdioConnection(cfg.transport)
    if isinstance(cfg.transport, HttpTransport):
        return HttpConnection(cfg.transport)
    raise ValueError(f"unknown transport {cfg.transport!r}")

class _ServerRuntime:
    def __init__(self, cfg: MCPServerConfig, conn: MCPConnection):
        self.cfg = cfg
        self.conn = conn
        self.registered_tool_names: list[str] = []
        self.resources: list[dict] = []

class MCPManager:
    def __init__(
        self,
        registry,
        connection_factory: Callable[[MCPServerConfig], MCPConnection] = _default_factory,
    ):
        self._registry = registry
        self._factory = connection_factory
        self._configs: dict[str, MCPServerConfig] = {}
        self._runtimes: dict[str, _ServerRuntime] = {}

    def add_config(self, cfg: MCPServerConfig) -> None:
        self._configs[cfg.server.id] = cfg

    async def start_all_autostart(self) -> None:
        await asyncio.gather(*(
            self.start_server(c.server.id)
            for c in self._configs.values()
            if c.server.enabled and c.server.autostart
        ), return_exceptions=True)

    async def start_server(self, server_id: str) -> None:
        if server_id in self._runtimes:
            return
        cfg = self._configs[server_id]
        if not cfg.server.enabled:
            raise RuntimeError(f"server {server_id!r} disabled")
        conn = self._factory(cfg)
        await conn.start()
        rt = _ServerRuntime(cfg, conn)
        self._runtimes[server_id] = rt
        try:
            await self._handshake(rt)
            await self._reconcile_tools(rt)
            await self._reconcile_resources(rt)
            self._wire_change_notifications(rt)
        except Exception:
            await self.stop_server(server_id)
            raise

    async def stop_server(self, server_id: str) -> None:
        rt = self._runtimes.pop(server_id, None)
        if rt is None:
            return
        for name in rt.registered_tool_names:
            self._registry.unregister(name)  # ensure ToolRegistry has unregister
        await rt.conn.stop()

    async def call_remote(self, server_id: str, tool_name: str, args: dict, timeout_ms: int) -> Any:
        rt = self._runtimes.get(server_id)
        if rt is None:
            await self.start_server(server_id)
            rt = self._runtimes[server_id]
        return await rt.conn.request(
            "tools/call", {"name": tool_name, "arguments": args},
            timeout=timeout_ms / 1000.0,
        )

    async def list_resources(self) -> list[dict]:
        out = []
        for sid, rt in self._runtimes.items():
            for r in rt.resources:
                out.append({"server_id": sid, **r})
        return out

    async def read_resource(self, server_id: str, uri: str) -> dict:
        rt = self._runtimes[server_id]
        return await rt.conn.request(
            "resources/read", {"uri": uri},
            timeout=rt.cfg.runtime.call_timeout_ms / 1000.0,
        )

    # --- internals ---

    async def _handshake(self, rt: _ServerRuntime) -> None:
        timeout = rt.cfg.runtime.init_timeout_ms / 1000.0
        await rt.conn.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "magi", "version": "0.1.0"},
        }, timeout=timeout)
        await rt.conn.notify("notifications/initialized")

    async def _reconcile_tools(self, rt: _ServerRuntime) -> None:
        for name in rt.registered_tool_names:
            self._registry.unregister(name)
        rt.registered_tool_names.clear()
        result = await rt.conn.request(
            "tools/list", None, timeout=rt.cfg.runtime.init_timeout_ms / 1000.0
        )
        for remote in result.get("tools") or []:
            override = rt.cfg.tool_overrides.get(remote["name"])
            cls = build_adapter_class(
                server_id=rt.cfg.server.id,
                remote=remote,
                manager=self,
                call_timeout_ms=rt.cfg.runtime.call_timeout_ms,
                override=override,
            )
            self._registry.register(cls)
            rt.registered_tool_names.append(f"mcp__{rt.cfg.server.id}__{remote['name']}")

    async def _reconcile_resources(self, rt: _ServerRuntime) -> None:
        try:
            result = await rt.conn.request(
                "resources/list", None,
                timeout=rt.cfg.runtime.init_timeout_ms / 1000.0,
            )
        except RuntimeError:
            rt.resources = []
            return
        rt.resources = result.get("resources") or []

    def _wire_change_notifications(self, rt: _ServerRuntime) -> None:
        rt.conn.on_notification(
            "notifications/tools/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_tools(rt)),
        )
        rt.conn.on_notification(
            "notifications/resources/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_resources(rt)),
        )
```

If `ToolRegistry` lacks an `unregister` method, **add one** in the lookup mixin (small focused change) — confirm by reading `registry_lookup.py` and adding if missing.

- [ ] **Step 5: Run tests, confirm pass**
- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/mcp/manager.py backend/src/magi/tools/ backend/tests/mcp/test_manager.py
git commit -m "feat(mcp): MCPManager with handshake, list, register"
```

### Task 9: Reconnect with backoff

**Files:**
- Modify: `backend/src/magi/mcp/manager.py` (add reconnect loop)
- Test: `backend/tests/mcp/test_manager_reconnect.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_unregister_on_disconnect_then_reconnect():
    # use a stub connection that fires a "disconnected" event after first call
    ...
```

(Author: write a stub connection where `state` flips to `DISCONNECTED` after a controlled trigger; verify manager unregisters then re-registers tools after `start_server` is called again. Keep test ≤ 40 lines.)

- [ ] **Step 2: Confirm fail**
- [ ] **Step 3: Add a `_watchdog` task per server in manager that observes `conn.state`. On disconnect: unregister tools, then attempt reconnect with backoff `[1, 2, 4, 8, 30]` capped at `cfg.runtime.max_restart_attempts`. After exhaustion, leave runtime in error state and log.
- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(mcp): auto-reconnect with exponential backoff"
```

---

## Chunk 4: Bootstrap wiring + permission risk hint plumbing

### Task 10: Wire `MCPManager` into bootstrap

**Files:**
- Modify: `backend/src/magi/bootstrap/` — find the file that wires `ToolRegistry` and `PluginManager` (read `backend/src/magi/bootstrap/` listing first), inject `MCPManager` after both exist.
- Modify: `backend/src/magi/config/models.py` — ensure `MAGI_HOME` (`~/.magi`) resolution is reused so loader points at `~/.magi/config/mcp/`.

- [ ] **Step 1: Read existing bootstrap to find the right seam**

```bash
ls backend/src/magi/bootstrap
grep -rn "ToolRegistry\|PluginManager" backend/src/magi/bootstrap | head
```

- [ ] **Step 2: Add `MCPManager` instantiation after `ToolRegistry` is built**, with config loaded from `~/.magi/config/mcp/` via `MCPConfigLoader`. Schedule `manager.start_all_autostart()` on app startup (use existing FastAPI lifespan or whichever pattern bootstrap already uses).
- [ ] **Step 3: Add a corresponding shutdown hook calling `stop_server` for each running server.**
- [ ] **Step 4: Add a small smoke test**

```python
# backend/tests/mcp/test_bootstrap_wiring.py
def test_mcp_manager_present_in_app():
    # construct app with empty ~/.magi/config/mcp; assert no crash
    ...
```

- [ ] **Step 5: Run unit + bootstrap tests**

`pytest backend/tests/mcp -v && pytest backend/tests/bootstrap -v`

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(mcp): wire MCPManager into backend bootstrap"
```

### Task 11: Permission risk hint plumbing

**Goal:** make sure `dangerous=true` flows into the permission gateway exactly the way internal dangerous tools do today. No new gateway logic; only verify and (if needed) add a thin metadata bridge.

**Files:**
- Read: `backend/src/magi/agent/control/permission/classifier.py`, `gateway.py`, `rules.py`
- Modify (minimal): wherever a tool is classified, ensure MCP-prefixed tools with `dangerous=True` produce the same `RiskLevel.HIGH` result as a built-in dangerous tool.
- Test: `backend/tests/mcp/test_permission_integration.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/mcp/test_permission_integration.py
import pytest
from magi.agent.control.permission.classifier import ToolRiskClassifier
from magi.mcp.tool_adapter import build_adapter_class

@pytest.mark.asyncio
async def test_destructive_mcp_tool_classified_high():
    cls = build_adapter_class(
        "demo",
        {"name":"rm","description":"","inputSchema":{"type":"object","properties":{}},
         "annotations":{"destructiveHint": True}},
        manager=None, call_timeout_ms=1000, override=None,
    )
    tool = cls()
    classifier = ToolRiskClassifier()
    result = classifier.classify(tool.get_schema(), parameters={})
    assert result.level.name in ("HIGH", "DESTRUCTIVE")

@pytest.mark.asyncio
async def test_readonly_mcp_tool_classified_low():
    cls = build_adapter_class(
        "demo",
        {"name":"ls","description":"","inputSchema":{"type":"object","properties":{}},
         "annotations":{"readOnlyHint": True}},
        manager=None, call_timeout_ms=1000, override=None,
    )
    tool = cls()
    classifier = ToolRiskClassifier()
    result = classifier.classify(tool.get_schema(), parameters={})
    assert result.level.name == "LOW"
```

(Adjust API names to match the real classifier signature found via reading.)

- [ ] **Step 2: Confirm fail (or surprisingly pass)**

If the existing classifier already keys off `schema.dangerous`, the tests should pass with just the adapter — verify this is the case.

If they fail, add the smallest possible bridge: e.g. extend the classifier's "dangerous → HIGH" rule, or attach a `risk_hint` to tools whose names start with `mcp__` based on the schema flag.

- [ ] **Step 3: Make tests pass with the smallest change**
- [ ] **Step 4: Run full permission test suite to ensure no regression**

`pytest backend/tests/agent/control/permission -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(mcp): ensure remote tool risk maps to permission gateway"
```

---

## Chunk 5: API + frontend settings surface

### Task 12: Backend API for MCP server management

**Files:**
- Create: `backend/src/magi/api/mcp_router.py`
- Modify: wherever routers are registered (find via `grep -rn "include_router" backend/src/magi/api`)
- Test: `backend/tests/api/test_mcp_router.py`

- [ ] **Step 1: Write failing tests for endpoints**

Endpoints (REST under `/api/mcp/`):
- `GET /servers` → list servers + status (`disconnected` | `connecting` | `connected` | `error`) + tool/resource counts + last error
- `POST /servers` → create new (body = config dict) → writes `~/.magi/config/mcp/<id>.toml`
- `PATCH /servers/{id}` → update fields (enabled, autostart, transport, etc.)
- `DELETE /servers/{id}` → stop + delete file
- `POST /servers/{id}/start` → manual start (resets restart counter)
- `POST /servers/{id}/stop` → manual stop
- `GET /servers/{id}/logs` → stderr tail + recent rpc summaries
- `GET /resources` → flat list (consumed by `@`-picker)
- `POST /resources/read` → `{server_id, uri}` → `{content, mimeType}`

- [ ] **Step 2: Confirm fail**

- [ ] **Step 3: Implement router. Persistence uses `MCPConfigLoader` + `tomli_w` (add to deps if not present) for round-tripping.**

- [ ] **Step 4: Run tests, confirm pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(mcp): REST API for server management + resources"
```

### Task 13: Frontend Settings page — MCP Servers list

**Files:**
- Create: `frontend/src/components/settings/MCPServersSection.tsx`
- Create: `frontend/src/components/settings/mcp/MCPServerRow.tsx`
- Create: `frontend/src/components/settings/mcp/MCPServerEditor.tsx`
- Create: `frontend/src/api/mcp.ts` — typed client for the new endpoints
- Modify: settings layout to include the new section (find via `grep -rn "MemorySettingsSections" frontend/src`)
- Test: `frontend/src/__tests__/MCPServersSection.test.tsx`

- [ ] **Step 1: Read existing settings section pattern** (e.g. `MemorySettingsSections.tsx`) to match style.
- [ ] **Step 2: Write failing component tests** (renders list, opens editor, calls API on save).
- [ ] **Step 3: Confirm fail**
- [ ] **Step 4: Implement**

Layout (mirror existing settings styling):
- list with rows: name, status badge, tool count, resource count, kebab menu (start/stop/edit/delete/import logs)
- editor drawer: id, name, transport kind (stdio/http) toggle, command/args/env or url/headers, advanced (timeouts, autostart, tool overrides as a JSON editor)
- import button: open file picker for `mcp.json` / `claude_desktop_config.json` and prefill.

- [ ] **Step 5: Run frontend tests**
- [ ] **Step 6: Commit**

```bash
git commit -am "feat(mcp): settings UI for MCP servers"
```

### Task 14: i18n strings

**Files:**
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`

- [ ] **Step 1: Add namespace `settings.mcp.*` with EN + zh-CN strings for every label used in Task 13.**
- [ ] **Step 2: Run i18n test** `pnpm test personalityI18n.test.ts` style suite (find via `grep -rn "i18n" frontend/src/__tests__`). If a key-coverage test exists, ensure it passes.
- [ ] **Step 3: Commit**

```bash
git commit -am "feat(mcp): i18n strings for settings ui"
```

---

## Chunk 6: Chat `@`-picker integration for resources

### Task 15: Resource attachment plumbing in chat

**Files:**
- Read: how chat composer builds attachments today (search `grep -rn "attachment" frontend/src/components/chat | head`).
- Modify: composer to add an "MCP Resources" tab/section to the existing `@` picker.
- Modify: chat send pipeline to include mounted resources as system attachment blocks.
- Modify: `backend/src/magi/chat/` (find the prompt builder) to inject resource content as a clearly-fenced read-only context block, with a 60s read-cache.
- Test: `backend/tests/chat/test_mcp_resource_attachment.py` + a frontend `__tests__` for the picker.

- [ ] **Step 1: Read existing attachment + composer code (no edits yet).**
- [ ] **Step 2: Write failing test** for the prompt builder: when an `MCPResourceAttachment` is present, the assembled prompt contains the resource text wrapped in `<mcp_resource uri="...">…</mcp_resource>`.
- [ ] **Step 3: Implement the prompt-builder change.**
- [ ] **Step 4: Implement the picker UI extension** — new section showing `mcp.list_resources()` results, grouped by server with description tooltip; selecting one calls `mcp.read_resource` and stores result in composer state.
- [ ] **Step 5: Wire send pipeline to forward attachments to the prompt builder.**
- [ ] **Step 6: Run backend + frontend tests.**
- [ ] **Step 7: Commit**

```bash
git commit -am "feat(mcp): @-mention picker mounts MCP resources into chat turn"
```

---

## Chunk 7: End-to-end smoke + docs

### Task 16: E2E smoke against `server-everything`

**Files:**
- Create: `backend/tests/mcp/test_e2e_everything.py`

- [ ] **Step 1: Mark test with `@pytest.mark.skipif(shutil.which('npx') is None, reason='npx not available')`.**
- [ ] **Step 2: Spin up `npx -y @modelcontextprotocol/server-everything` via `MCPManager` against a real `ToolRegistry`. Assert at least one tool registers, call it, assert success. Read at least one resource.**
- [ ] **Step 3: Run locally; document expected runtime in test docstring (~5s).**
- [ ] **Step 4: Commit**

```bash
git commit -am "test(mcp): e2e smoke against server-everything"
```

### Task 17: Developer docs

**Files:**
- Create: `docs/mcp-integration.md`

- [ ] **Step 1: Write a one-page reference**: how to add a server, where files live, transport options, tool naming, permission model, troubleshooting (logs in settings, stderr buffer, common errors). Link to spec.
- [ ] **Step 2: Add link from `docs/README.md` index.**
- [ ] **Step 3: Commit**

```bash
git commit -am "docs(mcp): integration reference"
```

---

## Done criteria

- [ ] All tests in `backend/tests/mcp/` and new frontend tests pass.
- [ ] Existing test suites (`backend/tests/agent`, `backend/tests/tools`, frontend) pass without regression.
- [ ] Manually configure one stdio server (`@modelcontextprotocol/server-filesystem`) and one HTTP server (any reachable test endpoint), confirm tools appear in chat and resources mount via `@` picker.
- [ ] In `PermissionMode.DEFAULT`, a `readOnlyHint` MCP tool runs without prompt; a `destructiveHint` MCP tool prompts via the existing `brokered_prompter`.
