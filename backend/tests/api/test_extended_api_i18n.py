from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from magi.api.routers import background_tasks as background_tasks_module
from magi.api.routers import commands as commands_module
from magi.api.routers import control as control_module
from magi.api.routers import mcp as mcp_module
from magi.api.routers import plugins_common as plugins_common_module
from magi.api.routers import timeline as timeline_module
from magi.api.routers.background_tasks import background_tasks_router
from magi.api.routers.commands import commands_router
from magi.api.routers.control import control_router
from magi.api.routers.local_embedding import local_embedding_router
from magi.api.routers.mcp import mcp_router
from magi.api.routers.plugins import plugins_router
from magi.api.routers.timeline import timeline_router
from magi.api.services.llm_testing_service import discover_openai_compatible_models
from magi.i18n import language_context
from magi.transport.http_middleware import LanguageContextMiddleware


from types import SimpleNamespace
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "language,expected",
    [("zh-CN", "不支持的模型发现格式"), ("en", "Unsupported model discovery format")],
)
async def test_unsupported_discovery_format_is_localized(language, expected):
    with language_context(language), pytest.raises(HTTPException) as captured:
        await discover_openai_compatible_models(
            base_url="https://example.invalid/v1", api_key=None, api_format="custom"
        )
    assert captured.value.status_code == 400
    assert captured.value.detail == expected


@pytest.mark.parametrize(
    "group,router,prefix,method,path,body,status,zh,en",
    [
        (
            "local_embedding",
            local_embedding_router,
            "/api/local-embedding",
            "POST",
            "/models/missing-model/download",
            None,
            404,
            "未知模型：missing-model",
            "Unknown model: missing-model",
        ),
        (
            "background_tasks",
            background_tasks_router,
            "/api/background-tasks",
            "GET",
            "",
            None,
            503,
            "后台任务管理器不可用",
            "Background task manager unavailable",
        ),
        (
            "control",
            control_router,
            "/api/control",
            "GET",
            "/rules",
            None,
            503,
            "权限规则存储不可用",
            "Permission rule store unavailable",
        ),
        (
            "mcp",
            mcp_router,
            "/api/mcp",
            "GET",
            "/servers",
            None,
            503,
            "MCP 管理器尚未初始化",
            "MCP manager not initialized",
        ),
        (
            "commands",
            commands_router,
            "/api/commands",
            "POST",
            "/run-skill-as-background",
            {"session_id": "s1", "skill_name": "ghost"},
            404,
            "未找到技能：'ghost'",
            "Skill 'ghost' not found",
        ),
        (
            "plugins",
            plugins_router,
            "/api/plugins",
            "GET",
            "/ghost/connections",
            None,
            404,
            "未找到插件",
            "Plugin not found",
        ),
        (
            "timeline",
            timeline_router,
            "/api/timeline",
            "GET",
            "/viewport?scale=day&start=1&end=2",
            None,
            503,
            "时间线服务不可用",
            "Timeline service unavailable",
        ),
    ],
    ids=["embedding", "background", "control", "mcp", "skill", "plugin", "timeline"],
)
def test_public_api_errors_follow_each_request_language(
    monkeypatch, group, router, prefix, method, path, body, status, zh, en
):
    def missing():
        raise RuntimeError("Dependency unavailable")

    monkeypatch.setattr(background_tasks_module, "resolve_background_task_manager", missing)
    monkeypatch.setattr(control_module, "resolve_permission_rule_store", missing)
    monkeypatch.setattr(mcp_module, "get_active_manager", lambda: None)
    monkeypatch.setattr(commands_module, "expand_skill", lambda **kwargs: None)
    monkeypatch.setattr(
        plugins_common_module,
        "resolve_plugin_manager",
        lambda: SimpleNamespace(get_package=lambda plugin_id: None),
    )
    monkeypatch.setattr(timeline_module, "get_unified_memory", missing)
    app = FastAPI()
    app.add_middleware(LanguageContextMiddleware)
    app.include_router(_build_public_router(router, _PUBLIC_ROUTE_METHODS[group]), prefix=prefix)
    with TestClient(app) as client:
        for language, expected in [("zh-CN", zh), ("en", en), ("zh-CN", zh)]:
            response = client.request(
                method, prefix + path, headers={"Accept-Language": language}, json=body
            )
            assert response.status_code == status
            assert response.json()["detail"] == expected
