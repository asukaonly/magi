"""Built-in IPC handlers for the Python worker."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import structlog

from magi.api.services import get_runtime_system_status

logger = structlog.get_logger(__name__)


def _is_json_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower()
    return "application/json" in normalized or normalized.endswith("+json")


def _is_text_content_type(content_type: str) -> bool:
    normalized = str(content_type or "").lower()
    if normalized.startswith("text/"):
        return True
    return any(token in normalized for token in ("application/xml", "application/javascript", "image/svg+xml"))


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

        url = path
        if query:
            url = f"{path}?{query}"

        kwargs: dict[str, Any] = {"headers": headers}
        if body_file_path:
            staged_path = Path(body_file_path)
            if not staged_path.is_file():
                return {"status": 400, "body": {"detail": "Missing staged request body file"}}
            kwargs["content"] = staged_path.read_bytes()
        elif body is not None:
            kwargs["content"] = json.dumps(body).encode("utf-8") if not isinstance(body, (str, bytes)) else (
                body.encode("utf-8") if isinstance(body, str) else body
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

    async def close(self) -> None:
        await self._client.aclose()
