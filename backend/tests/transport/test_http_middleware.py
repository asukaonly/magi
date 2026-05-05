from __future__ import annotations

import pytest
from fastapi import Request, Response

from magi.i18n import get_current_language as get_core_current_language
from magi.plugins.i18n import get_current_language as get_plugin_current_language
from magi.transport.http_middleware import LanguageContextMiddleware


async def _disconnected_receive() -> dict:
    return {"type": "http.disconnect"}


async def _connected_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


def _build_request(receive, headers: list[tuple[bytes, bytes]] | None = None) -> Request:  # type: ignore[no-untyped-def]
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/messages/sessions",
            "raw_path": b"/api/messages/sessions",
            "query_string": b"",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_language_context_middleware_sets_core_and_plugin_language_context() -> None:
    middleware = LanguageContextMiddleware(app=lambda scope, receive, send: None)
    request = _build_request(
        _connected_receive,
        headers=[(b"accept-language", b"en-US,en;q=0.9")],
    )

    async def _inspect_language(_request: Request):  # type: ignore[no-untyped-def]
        assert get_core_current_language() == "en"
        assert get_plugin_current_language() == "en"
        return Response(status_code=200)

    response = await middleware.dispatch(request, _inspect_language)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_language_context_middleware_ignores_client_disconnect_runtime_error() -> None:
    middleware = LanguageContextMiddleware(app=lambda scope, receive, send: None)
    request = _build_request(_disconnected_receive)

    async def _raise_no_response(_request: Request):  # type: ignore[no-untyped-def]
        raise RuntimeError("No response returned.")

    response = await middleware.dispatch(request, _raise_no_response)

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_language_context_middleware_keeps_real_no_response_errors() -> None:
    middleware = LanguageContextMiddleware(app=lambda scope, receive, send: None)
    request = _build_request(_connected_receive)

    async def _raise_no_response(_request: Request):  # type: ignore[no-untyped-def]
        raise RuntimeError("No response returned.")

    with pytest.raises(RuntimeError, match="No response returned."):
        await middleware.dispatch(request, _raise_no_response)
