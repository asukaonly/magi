from __future__ import annotations

from fastapi import FastAPI

from magi.api.routes import register_api_routes


def _build_registered_paths() -> set[str]:
    app = FastAPI()
    register_api_routes(app)
    return set(app.openapi()["paths"].keys())


def test_register_api_routes_keeps_only_supported_public_surfaces() -> None:
    paths = _build_registered_paths()

    assert "/api/messages/send" in paths
    assert "/api/messages/session/{session_id}/attachments" in paths
    assert "/api/messages/session/{session_id}/workspace" in paths
    assert "/api/messages/session/{session_id}/cancel-run" in paths
    assert "/api/messages/session/{session_id}/message/{message_id}/label" in paths
    assert "/api/messages/session/{session_id}/message/{message_id}" in paths
    assert "/api/config/" in paths
    assert "/api/llm/providers/catalog" in paths
    assert "/api/llm/providers/custom-template" in paths
    assert "/api/plugins" in paths
    assert "/api/timeline/viewport" in paths
    assert "/api/timeline/context/{anchor_id}" in paths
    assert "/api/tools/config" in paths
    assert "/api/metrics/runtime/overview" in paths
    assert "/api/skills/" in paths
    assert "/api/memory/identity/links" in paths
    assert "/api/memory/l2/microbatch-flush" in paths


def test_register_api_routes_excludes_deprecated_and_internal_surfaces() -> None:
    paths = _build_registered_paths()

    assert "/api/agents/" not in paths
    assert "/api/tasks/" not in paths
    assert "/api/others/list" not in paths

    assert "/api/tools/" not in paths
    assert "/api/tools/export/claude" not in paths
    assert "/api/tools/import/claude" not in paths

    assert "/api/metrics/agents" not in paths
    assert "/api/metrics/performance" not in paths

    assert "/api/messages/sensor/status" not in paths
    assert "/api/messages/worker/{worker_id}" not in paths

    assert "/api/skills/{skill_name}" not in paths
    assert "/api/skills/{skill_name}/execute" not in paths
    assert "/api/skills/refresh" not in paths

    assert "/api/config/reset" not in paths
    assert "/api/config/llm-providers" not in paths

    assert "/api/memory/eval/query" not in paths
    assert "/api/memory/eval/replay" not in paths
    assert "/api/memory/eval/finalize-replay" not in paths
    assert "/api/memory/background/pending" not in paths
    assert "/api/memory/clear" not in paths
