from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
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


def _localized_client(router: APIRouter, *, prefix: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(LanguageContextMiddleware)
    app.include_router(router, prefix=prefix)
    return TestClient(app)


@pytest.mark.asyncio
async def test_llm_model_discovery_unsupported_format_uses_chinese() -> None:
    with language_context("zh-CN"):
        with pytest.raises(HTTPException) as exc_info:
            await discover_openai_compatible_models(
                base_url="https://example.invalid/v1",
                api_key=None,
                api_format="custom",
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "不支持的模型发现格式"


def test_local_embedding_unknown_model_uses_chinese() -> None:
    client = _localized_client(local_embedding_router, prefix="/api/local-embedding")

    response = client.post(
        "/api/local-embedding/models/missing-model/download",
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "未知模型：missing-model"


def test_background_task_manager_unavailable_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing_manager():
        raise RuntimeError("missing")

    monkeypatch.setattr(
        background_tasks_module, "resolve_background_task_manager", _missing_manager
    )
    client = _localized_client(background_tasks_router, prefix="/api/background-tasks")

    response = client.get("/api/background-tasks", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 503
    assert response.json()["detail"] == "后台任务管理器不可用"


def test_control_rule_store_unavailable_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing_rule_store():
        raise RuntimeError("missing")

    monkeypatch.setattr(control_module, "resolve_permission_rule_store", _missing_rule_store)
    client = _localized_client(control_router, prefix="/api/control")

    response = client.get("/api/control/rules", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 503
    assert response.json()["detail"] == "权限规则存储不可用"


def test_mcp_manager_uninitialized_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_module, "get_active_manager", lambda: None)
    client = _localized_client(mcp_router, prefix="/api/mcp")

    response = client.get("/api/mcp/servers", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 503
    assert response.json()["detail"] == "MCP 管理器尚未初始化"


def test_commands_missing_skill_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands_module, "expand_skill", lambda **kwargs: None)
    client = _localized_client(commands_router, prefix="/api/commands")

    response = client.post(
        "/api/commands/run-skill-as-background",
        headers={"Accept-Language": "zh-CN"},
        json={"session_id": "s1", "skill_name": "ghost"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到技能：'ghost'"


def test_plugins_missing_package_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MissingPluginManager:
        def get_package(self, plugin_id: str):
            return None

    monkeypatch.setattr(
        plugins_common_module,
        "resolve_plugin_manager",
        lambda: _MissingPluginManager(),
    )
    client = _localized_client(plugins_router, prefix="/api/plugins")

    response = client.get("/api/plugins/ghost/settings", headers={"Accept-Language": "zh-CN"})

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到插件"


def test_timeline_service_unavailable_uses_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    def _missing_memory():
        raise RuntimeError("missing")

    monkeypatch.setattr(timeline_module, "get_unified_memory", _missing_memory)
    client = _localized_client(timeline_router, prefix="/api/timeline")

    response = client.get(
        "/api/timeline/viewport?scale=day&start=1&end=2",
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "时间线服务不可用"
