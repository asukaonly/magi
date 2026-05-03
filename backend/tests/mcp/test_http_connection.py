import asyncio
import json
import socket
from threading import Thread

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from magi.mcp.config import HttpTransport
from magi.mcp.connection import HttpConnection


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def http_server_factory():
    """Run a FastAPI app under uvicorn in a thread; yield (url, app)."""

    started = []

    def _start(app: FastAPI):
        port = _free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning"
        )
        server = uvicorn.Server(config)
        thread = Thread(target=server.run, daemon=True)
        thread.start()
        import time

        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("uvicorn did not start")
        started.append((server, thread))
        return f"http://127.0.0.1:{port}/mcp"

    yield _start

    for server, thread in started:
        server.should_exit = True
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_http_inline_json_response(http_server_factory):
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(req: Request):
        body = await req.json()
        if body.get("method") == "echo":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": body["params"],
                }
            )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {"code": -1, "message": "x"},
            }
        )

    @app.get("/mcp")
    async def get_mcp():
        return Response(status_code=405)

    url = http_server_factory(app)
    conn = HttpConnection(HttpTransport(url=url))
    await conn.start()
    try:
        result = await conn.request("echo", {"x": 1}, timeout=3.0)
        assert result == {"x": 1}
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_http_sse_response(http_server_factory):
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(req: Request):
        body = await req.json()

        async def gen():
            await asyncio.sleep(0.01)
            payload = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"streamed": True},
                }
            )
            yield f"data: {payload}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/mcp")
    async def get_mcp():
        return Response(status_code=405)

    url = http_server_factory(app)
    conn = HttpConnection(HttpTransport(url=url))
    await conn.start()
    try:
        result = await conn.request("anything", {}, timeout=3.0)
        assert result == {"streamed": True}
    finally:
        await conn.stop()


@pytest.mark.asyncio
async def test_http_session_id_propagated(http_server_factory):
    app = FastAPI()
    seen_session = {}

    @app.post("/mcp")
    async def mcp(req: Request):
        body = await req.json()
        if body.get("method") == "initialize":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}},
                headers={"Mcp-Session-Id": "sess-abc"},
            )
        seen_session["v"] = req.headers.get("mcp-session-id")
        return JSONResponse(
            {"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}}
        )

    @app.get("/mcp")
    async def get_mcp():
        return Response(status_code=405)

    url = http_server_factory(app)
    conn = HttpConnection(HttpTransport(url=url))
    await conn.start()
    try:
        await conn.request("initialize", {}, timeout=3.0)
        await conn.request("ping", {}, timeout=3.0)
        assert seen_session["v"] == "sess-abc"
    finally:
        await conn.stop()
