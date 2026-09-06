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
    assert "/api/messages/session/{session_id}/detach-run" in paths
    assert "/api/messages/session/{session_id}/message/{message_id}/label" in paths
    assert "/api/messages/session/{session_id}/message/{message_id}" in paths
    assert "/api/config/" in paths
    assert "/api/config/embedding-preflight" in paths
    assert "/api/config/preferences/language" in paths
    assert "/api/config/onboarding-status" in paths
    assert "/api/config/onboarding-draft" in paths
    assert "/api/config/onboarding-complete" in paths
    assert "/api/llm/providers/catalog" in paths
    assert "/api/llm/providers/custom-template" in paths
    assert "/api/personality/generate" in paths
    assert "/api/personality/greeting" in paths
    assert "/api/personality/bootstrap/init" in paths
    assert "/api/personas/" in paths
    assert "/api/personas/active" in paths
    assert "/api/personas/seed-previews" in paths
    assert "/api/personalities/" in paths
    assert "/api/plugins" in paths
    assert "/api/plugins/{plugin_id}/update" in paths
    assert "/api/plugins/connections/{connection_id}/settings/resources/{resource_name}" in paths
    assert "/api/plugins/connections/{connection_id}/settings/actions/{action_id}/start" in paths
    assert (
        "/api/plugins/connections/{connection_id}/settings/actions/{action_id}/sessions/{session_id}/poll" in paths
    )
    assert (
        "/api/plugins/connections/{connection_id}/settings/actions/{action_id}/sessions/{session_id}/cancel"
        in paths
    )
    assert "/api/sources/status" in paths
    assert "/api/sources/{source_name}/flush-state" in paths
    assert "/api/sources/{source_name}/authorize" in paths
    assert "/api/timeline/viewport" in paths
    assert "/api/timeline/cover" in paths
    assert "/api/timeline/context/{anchor_id}" in paths
    assert "/api/tools/config" in paths
    assert "/api/skills/" in paths
    assert "/api/memory/identity/links" in paths
    assert "/api/memory/clear" in paths
    assert "/api/memory/l2/projection-flush" in paths
    assert "/api/memory/eval/replay" in paths
    assert "/api/memory/eval/query" in paths
    assert "/api/memory/eval/judge-answer" in paths
    assert "/api/memory/eval/finalize-replay" in paths
    assert "/api/memory/background/pending" in paths
    assert "/api/memory/embeddings/status" in paths
    assert "/api/memory/embeddings/rebuild" in paths
    assert "/api/memory/embeddings/rebuild/{job_id}" in paths
    assert "/api/memory/embeddings/rebuild/{job_id}/cancel" in paths
    assert "/api/memory/stories" in paths
    assert "/api/memory/stories/{summary_id}/review" in paths
    assert "/api/memory/stories/{summary_id}/evidence" in paths
    assert "/api/memory/portrait" in paths
    assert "/api/memory/portrait/self" in paths
    assert "/api/memory/history-imports/markdown/preview" in paths
    assert "/api/memory/history-imports/{job_id}/markdown/append" in paths
    assert "/api/memory/history-imports/importers" in paths
    assert "/api/memory/history-imports/importers/{plugin_id}/{importer_id}/preview" in paths
    assert "/api/memory/history-imports" in paths
    assert "/api/memory/history-imports/{job_id}" in paths
    assert "/api/memory/history-imports/{job_id}/source-preview" in paths
    assert "/api/memory/history-imports/{job_id}/selection" in paths
    assert "/api/memory/history-imports/{job_id}/confirm" in paths
    assert "/api/memory/history-imports/{job_id}/resume" in paths
    assert "/api/profile/me" in paths
    assert "/api/profile/me/refresh" in paths
    assert "/api/control/sessions/{session_id}/permissions" in paths
    assert "/api/memory/l2/episodes/reconsolidate" in paths


def test_register_api_routes_exposes_only_l2_assertion_confirmation_feedback() -> None:
    app = FastAPI()
    register_api_routes(app)
    openapi_paths = app.openapi()["paths"]

    feedback = openapi_paths.get("/api/memory/l2/assertions/{assertion_id}/feedback", {})

    assert "patch" in feedback, "assertion confirmation PATCH must be public"
    assert "/api/memory/l2/assertions/{assertion_id}/correct" not in openapi_paths
    assert "/api/memory/l2/edges/{triple_id}/reject" not in openapi_paths


def test_history_import_confirmation_exposes_source_and_identity_scope() -> None:
    app = FastAPI()
    register_api_routes(app)
    schema = app.openapi()["components"]["schemas"]["HistoryImportConfirmBody"]

    assert set(schema["properties"]) == {
        "confirm_personal_writing",
        "included_source_ids",
        "self_participant_ids",
    }


def test_register_api_routes_excludes_deprecated_and_internal_surfaces() -> None:
    paths = _build_registered_paths()

    # metrics/schedules/tasks are now native Rust endpoints — not registered in Python
    assert "/api/metrics/runtime/overview" not in paths
    assert "/api/schedules/" not in paths
    assert "/api/tasks/" not in paths

    assert "/api/agents/" not in paths
    assert "/api/others/list" not in paths

    assert "/api/tools/" not in paths
    assert "/api/tools/export/claude" not in paths
    assert "/api/tools/import/claude" not in paths

    assert "/api/metrics/agents" not in paths
    assert "/api/metrics/performance" not in paths

    assert "/api/messages/source/status" not in paths
    assert "/api/messages/worker/{worker_id}" not in paths

    assert "/api/skills/{skill_name}" not in paths
    assert "/api/skills/{skill_name}/execute" not in paths
    assert "/api/skills/refresh" not in paths

    assert "/api/config/reset" not in paths
    assert "/api/config/llm-providers" not in paths

    assert "/api/personality/" not in paths
    assert "/api/personality/current" not in paths
    assert "/api/personality/compare/{from_name}/{to_name}" not in paths
    assert "/api/personality/{name}" not in paths
