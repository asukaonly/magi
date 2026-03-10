"""Tests for tool router route matching."""

import pytest
from starlette.routing import Match

from magi.api.routers.tools import _build_tool_config_response, list_tools_with_config, tools_router
from magi.tools.builtin.web_fetch_tool import WebFetchTool


def test_tools_config_route_matches_static_endpoint_first():
    scope = {
        "type": "http",
        "path": "/config",
        "method": "GET",
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    for route in tools_router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            assert route.endpoint is list_tools_with_config
            return

    pytest.fail("Expected /config to match the static tool config endpoint")


def test_web_fetch_config_response_uses_default_provider():
    response = _build_tool_config_response("web-fetch", WebFetchTool())

    assert response.enabled is True
    assert response.current_values["default_provider"] == "http"
