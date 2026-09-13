"""Transport result confirmation for two explicitly selected plugin mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, JsonValue
from starlette.responses import JSONResponse, Response

from ...core.container import get_container
from ...plugins.operation_execution import plugin_runtime_operation

_ID = re.compile(r"^(\d{13})-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_ACTIVE: set[asyncio.Task[Response]] = set()


class PluginRpcReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str
    state: Literal["running", "completed", "uncertain"]
    http_status: int | None
    result: JsonValue


PLUGIN_RPC_OPENAPI = {"parameters": [
    {"name": "X-Magi-Request-Id", "in": "header", "required": True,
     "schema": {"type": "string"}, "description": "Stable issued-at milliseconds plus UUID, retained across retries."},
    {"name": "X-Magi-Data-Epoch", "in": "header", "required": True,
     "schema": {"type": "string"}, "description": "Data epoch of the selected authenticated center."},
]}


def rpc_identity(request: Request, operation_id: str, *, writing: bool = True) -> tuple[str, str, int]:
    peer = request.headers.get("x-magi-client-id")
    epoch = request.headers.get("x-magi-data-epoch")
    if not peer:
        raise HTTPException(401, "Authenticated device identity is required")
    if not epoch or epoch != os.environ.get("MAGI_DATA_EPOCH"):
        raise HTTPException(409, "Service data changed; reload before continuing")
    match = _ID.fullmatch(operation_id)
    now = int(time.time() * 1000)
    window = 86400000 if writing else 7 * 86400000
    if not match or not now - window <= int(match[1]) <= now + 300000:
        raise HTTPException(409, "Request identity is invalid or expired; confirm the outcome before starting again")
    return peer, epoch, int(match[1])


def _response(snapshot: dict) -> Response:
    if snapshot["state"] == "completed":
        return JSONResponse(snapshot["result"], status_code=snapshot["http_status"])
    return JSONResponse(snapshot, status_code=202)


class ConfirmedPluginRpcRoute(APIRoute):
    """Keep an admitted attempt alive through caller timeout; never replay uncertain work."""

    def get_route_handler(self):
        original = super().get_route_handler()
        selected = "POST" in self.methods and (
            self.path.endswith("/{plugin_id}/connections")
            or self.path.endswith("/settings/actions/{action_id}/start")
        )
        if not selected:
            return original

        async def handle(request: Request) -> Response:
            operation_id = request.headers.get("x-magi-request-id", "")
            peer, epoch, issued = rpc_identity(request, operation_id)
            try:
                payload = await request.json()
            except ValueError as exc:
                raise HTTPException(422, "Plugin request body is invalid") from exc
            fingerprint = hashlib.sha256(json.dumps(
                [operation_id, request.url.path, payload], sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            connection_id = request.path_params.get("connection_id")
            store = get_container().runtime_trace_store()

            async def execute() -> Response:
                async with plugin_runtime_operation():
                    try:
                        admitted, snapshot = await store.claim_plugin_rpc(
                            client_id=peer, epoch=epoch, operation_id=operation_id,
                            fingerprint=fingerprint, issued_at_ms=issued, connection_id=connection_id,
                        )
                    except ValueError as exc:
                        raise HTTPException(409, str(exc)) from exc
                    except (sqlite3.Error, RuntimeError) as exc:
                        raise HTTPException(503, "Plugin request receipt storage is unavailable") from exc
                    if not admitted:
                        return _response(snapshot)
                    status_code, result, result_connection = None, None, connection_id
                    try:
                        try:
                            response = await original(request)
                            status_code = response.status_code
                            result = json.loads(bytes(response.body))
                        except RequestValidationError:
                            status_code, result = 422, {"detail": "Plugin request is invalid"}
                        except HTTPException as exc:
                            status_code, result = exc.status_code, {"detail": exc.detail}
                        if isinstance(result, dict) and isinstance(result.get("connection_id"), str):
                            result_connection = result["connection_id"]
                    except Exception:
                        # An arbitrary failure may occur after an external effect was committed.
                        status_code, result = None, None
                    finally:
                        await store.finish_plugin_rpc(
                            client_id=peer, epoch=epoch, operation_id=operation_id,
                            http_status=status_code, result=result, connection_id=result_connection,
                        )
                    snapshot = await store.read_plugin_rpc(peer, epoch, operation_id)
                    return _response(snapshot)

            task = asyncio.create_task(execute())
            _ACTIVE.add(task)
            def completed(done: asyncio.Task[Response]) -> None:
                _ACTIVE.discard(done)
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(completed)
            # The lifecycle/receipt owner survives a disconnected or timed-out HTTP caller.
            return await asyncio.shield(task)

        return handle
