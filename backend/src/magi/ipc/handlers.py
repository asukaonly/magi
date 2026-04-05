"""Built-in IPC handlers for the Python worker."""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def handle_ping(params: dict[str, Any] | None) -> dict[str, str]:
    """Health-check ping — returns pong."""
    return {"status": "pong"}


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

        url = path
        if query:
            url = f"{path}?{query}"

        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["content"] = json.dumps(body).encode("utf-8") if not isinstance(body, (str, bytes)) else (
                body.encode("utf-8") if isinstance(body, str) else body
            )
            if "content-type" not in {k.lower() for k in headers}:
                kwargs["headers"] = {**headers, "content-type": "application/json"}

        try:
            resp = await self._client.request(method, url, **kwargs)
            # Try to return JSON body
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = resp.text
            return {
                "status": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp_body,
            }
        except Exception as exc:
            logger.exception("api_forward_error", path=path, method=method)
            return {"status": 500, "body": {"detail": str(exc)}}

    async def close(self) -> None:
        await self._client.aclose()

