"""Built-in IPC handlers for the Python worker."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import structlog

from magi.api.services import get_runtime_system_status

logger = structlog.get_logger(__name__)
_STAGED_BODY_CHUNK_BYTES = 1024 * 1024
_STAGED_BODY_FILE_PREFIX = "magi-ipc-body-"
_MAX_STAGED_BODY_BYTES = 55 * 1024 * 1024


def _is_json_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower()
    return "application/json" in normalized or normalized.endswith("+json")


def _is_text_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower()
    if normalized.startswith("text/"):
        return True
    return any(
        token in normalized
        for token in ("application/xml", "application/javascript", "image/svg+xml")
    )


def _open_staged_request_body(path: Path) -> int:
    """Open one private gateway staging file without a path-swap window."""

    try:
        file_stat = path.lstat()
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Staged request body file is not available") from exc
    if (
        parent != temp_root
        or not path.name.startswith(_STAGED_BODY_FILE_PREFIX)
        or not stat.S_ISREG(file_stat.st_mode)
    ):
        raise ValueError("Staged request body file is outside the IPC staging boundary")
    _validate_staged_request_body_stat(file_stat)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("Staged request body file is not available") from exc
    try:
        opened_stat = os.fstat(descriptor)
        _validate_staged_request_body_stat(opened_stat)
        if (
            opened_stat.st_dev,
            opened_stat.st_ino,
        ) != (
            file_stat.st_dev,
            file_stat.st_ino,
        ):
            raise ValueError("Staged request body file changed before forwarding")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _validate_staged_request_body_stat(file_stat: os.stat_result) -> None:
    """Require one opened staging file to retain its private-file contract."""

    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("Staged request body file is outside the IPC staging boundary")
    if file_stat.st_size > _MAX_STAGED_BODY_BYTES:
        raise ValueError("Staged request body file exceeds the forwarding limit")
    if hasattr(file_stat, "st_nlink") and file_stat.st_nlink != 1:
        raise ValueError("Staged request body file has an unexpected link count")
    if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
        raise ValueError("Staged request body file has an unexpected owner")
    if os.name != "nt" and file_stat.st_mode & 0o077:
        raise ValueError("Staged request body file permissions are too broad")


async def _open_staged_request_body_async(path: Path) -> int:
    """Close a late-opened descriptor when the forwarding task is cancelled."""

    worker = asyncio.create_task(asyncio.to_thread(_open_staged_request_body, path))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            descriptor = await worker
        except BaseException:
            pass
        else:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise


async def _stream_staged_request_body(descriptor: int):
    """Yield a staged IPC request without materializing the whole file."""

    total_bytes = 0
    while chunk := await _read_staged_request_body_chunk(descriptor):
        total_bytes += len(chunk)
        if total_bytes > _MAX_STAGED_BODY_BYTES:
            raise ValueError("Staged request body grew beyond the forwarding limit")
        yield chunk


async def _read_staged_request_body_chunk(descriptor: int) -> bytes:
    """Finish an in-flight file read before its descriptor can be closed."""

    worker = asyncio.create_task(
        asyncio.to_thread(
            os.read,
            descriptor,
            _STAGED_BODY_CHUNK_BYTES,
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        try:
            await worker
        except BaseException:
            pass
        raise


async def handle_ping(params: dict[str, Any] | None) -> dict[str, str]:
    """Health-check ping — returns pong."""
    return {"status": "pong"}


class RuntimeReadyHandler:
    """Returns worker readiness over IPC without routing through HTTP forwarding."""

    def __init__(self, asgi_app: Any) -> None:
        self._asgi_app = asgi_app

    async def handle(self, params: dict[str, Any] | None) -> dict[str, Any]:
        _ = params
        runtime_status = await get_runtime_system_status(self._asgi_app)
        return {
            "success": True,
            "message": "Backend startup state",
            "data": {
                "ready": runtime_status["runtime_ready"]
                and runtime_status["queue_backlog_healthy"],
                "status": runtime_status["status"],
                "runtime_ready": runtime_status["runtime_ready"],
                "worker_ready": runtime_status["worker_ready"],
                "llm_ready": runtime_status["llm_ready"],
                "agent_runtime_ready": runtime_status["agent_runtime_ready"],
                "runtime_status": runtime_status["runtime_status"],
                "startup_state": runtime_status["startup_state"],
                "deferred_reason": runtime_status["deferred_reason"],
                "queue_backlog_healthy": runtime_status["queue_backlog_healthy"],
                "pending_commands": runtime_status["pending_commands"],
            },
        }


class ApiForwardHandler:
    """Forwards HTTP-like requests from the Rust gateway to the FastAPI ASGI app."""

    def __init__(self, asgi_app: Any) -> None:
        import httpx  # noqa: E402

        self._transport = httpx.ASGITransport(app=asgi_app)
        self._client = httpx.AsyncClient(transport=self._transport, base_url="http://ipc")

    async def handle(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Dispatch an IPC api.forward request to the internal FastAPI app.

        Params:
            method: HTTP method (GET, POST, etc.)
            path: request path (/api/...)
            query: query string (optional, without leading ?)
            headers: dict of headers (optional)
            body: request body (optional, as JSON-serialisable value)
        """
        if not params:
            return {"status": 400, "body": {"detail": "Missing params"}}

        method = params.get("method", "GET").upper()
        path = params.get("path", "/")
        query = params.get("query", "")
        headers = params.get("headers", {})
        body = params.get("body")
        body_file_path = str(params.get("body_file_path") or "").strip()
        staged_descriptor: int | None = None

        url = path
        if query:
            url = f"{path}?{query}"

        kwargs: dict[str, Any] = {"headers": headers}
        if body_file_path:
            try:
                staged_descriptor = await _open_staged_request_body_async(Path(body_file_path))
            except ValueError as exc:
                return {"status": 400, "body": {"detail": str(exc)}}
            kwargs["content"] = _stream_staged_request_body(staged_descriptor)
        elif body is not None:
            kwargs["content"] = (
                json.dumps(body).encode("utf-8")
                if not isinstance(body, (str, bytes))
                else (body.encode("utf-8") if isinstance(body, str) else body)
            )
            if "content-type" not in {k.lower() for k in headers}:
                kwargs["headers"] = {**headers, "content-type": "application/json"}

        try:
            resp = await self._client.request(method, url, **kwargs)
            result = {
                "status": resp.status_code,
                "headers": dict(resp.headers),
            }
            content_type = str(resp.headers.get("content-type") or "")

            if _is_json_content_type(content_type):
                try:
                    result["body"] = resp.json()
                except Exception:
                    result["body"] = resp.text
                return result

            if _is_text_content_type(content_type):
                result["body"] = resp.text
                return result

            body_bytes = resp.content or b""
            result["body_base64"] = base64.b64encode(body_bytes).decode("ascii")
            result["body_encoding"] = "base64"
            return result
        except Exception as exc:
            logger.exception("api_forward_error", path=path, method=method)
            return {"status": 500, "body": {"detail": str(exc)}}
        finally:
            if staged_descriptor is not None:
                try:
                    os.close(staged_descriptor)
                except OSError:
                    pass

    async def close(self) -> None:
        await self._client.aclose()
