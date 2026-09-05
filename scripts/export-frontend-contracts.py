#!/usr/bin/env python3
"""Export response contracts from the production configuration models."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from pydantic import TypeAdapter
from pydantic.json_schema import GenerateJsonSchema, models_json_schema
from pydantic_core import core_schema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "sdk" / "src"))


class ResponseJsonSchema(GenerateJsonSchema):
    """Describe full model serialization, including default-valued fields."""

    def field_is_required(
        self,
        field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if self.mode == "serialization" and field["type"] in {"model-field", "dataclass-field"}:
            return field.get("serialization_exclude_if") is None
        return super().field_is_required(field, total)


def build_contract() -> dict:
    from magi.api.routers.config import config_router
    from magi.api.routers.config_schemas import (
        ConfigResponse,
        OnboardingStatusResponse,
        OnboardingTemplateResponse,
    )
    from magi.api.routers.tools import (
        ToolConfigResponse,
        ToolsListResponse,
        tools_router,
    )
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    from magi.api.routers.code_agent import (
        code_agent_router, CodeAgentSettingsResponse, CodeAgentProbeResponse,
    )
    public_code = _build_public_router(code_agent_router, _PUBLIC_ROUTE_METHODS["code_agent"])
    for method, path, model in [
        ("GET", "/settings", CodeAgentSettingsResponse), ("PATCH", "/settings", CodeAgentSettingsResponse),
        ("GET", "/probe", CodeAgentProbeResponse), ("POST", "/rescan", CodeAgentProbeResponse),
    ]:
        if not any(route.path == path and method in route.methods and route.response_model is model for route in public_code.routes):
            raise RuntimeError(f"Code tool settings contract is not exposed: {method} {path}")

    public = _build_public_router(config_router, _PUBLIC_ROUTE_METHODS["config"])
    contracts = {
        ("GET", "/"): ConfigResponse,
        ("PUT", "/"): ConfigResponse,
        ("PUT", "/preferences/language"): ConfigResponse,
        ("GET", "/template"): ConfigResponse,
        ("PUT", "/onboarding-draft"): ConfigResponse,
        ("POST", "/onboarding-complete"): ConfigResponse,
        ("GET", "/onboarding-status"): OnboardingStatusResponse,
        ("GET", "/onboarding-template"): OnboardingTemplateResponse,
    }
    for (method, path), model in contracts.items():
        route = next((route for route in public.routes if route.path == path and method in route.methods), None)
        if route is None or route.response_model is not model:
            raise RuntimeError(f"Configuration contract is not exposed by the public router: {method} {path}")
        if route.response_model_exclude_none or route.response_model_exclude_unset or route.response_model_exclude_defaults:
            raise RuntimeError(f"Configuration response must serialize complete fields: {method} {path}")

    public_tools = _build_public_router(tools_router, _PUBLIC_ROUTE_METHODS["tools"])
    for path, model in [("/config", ToolsListResponse), ("/{tool_name}/config", ToolConfigResponse)]:
        if not any(route.path == path and "GET" in route.methods and route.response_model is model for route in public_tools.routes):
            raise RuntimeError(f"Tool configuration contract is not exposed: {path}")

    _, document = models_json_schema(
        [(model, "serialization") for model in (
            ConfigResponse, OnboardingStatusResponse, OnboardingTemplateResponse, ToolConfigResponse, ToolsListResponse,
            CodeAgentSettingsResponse, CodeAgentProbeResponse,
        )],
        schema_generator=ResponseJsonSchema,
        ref_template="#/components/schemas/{model}",
    )
    return {
        "openapi": "3.1.0",
        "info": {"title": "Magi configuration response contracts", "version": "1"},
        "paths": {},
        "components": {"schemas": document["$defs"]},
    }


def build_examples() -> dict:
    from magi.api.routers.config_schemas import (
        ConfigResponse,
        LLMProviderConfigModel,
        OnboardingStatusDataModel,
        OnboardingStatusResponse,
        OnboardingTemplateDataModel,
        OnboardingTemplateResponse,
        SystemConfigModel,
    )
    from magi.api.routers.tools import ToolConfigResponse, ToolConfigSpecResponse

    from magi.api.routers.code_agent import CodeAgentSettingsResponse, CodeAgentProbeResponse, CodeAgentProbeResults
    from magi.tools.code_agent.settings import CodeAgentSettings
    from magi.tools.code_agent.contracts import ProbeResult

    config = SystemConfigModel()
    config.memory.db_path = "/fixture/magi/data/memory"
    config.memory.archive_path = "/fixture/magi/data/memory/archive"
    config.preferences.default_chat_workspace_path = "/fixture/magi/chat-workspace"
    config.llm.providers["openai"] = LLMProviderConfigModel()
    for selection in config.llm.selections.values():
        selection.provider_id = "openai"
        selection.model = "fixture-model"
    return {
        "codeAgentSettings": CodeAgentSettingsResponse(settings=CodeAgentSettings(), workspace_used=None).model_dump(mode="json"),
        "codeAgentProbe": CodeAgentProbeResponse(results=CodeAgentProbeResults(**{
            name: ProbeResult(name=name, installed=False, binary_path=None, version=None, detected_at=1, error=None, extras={})
            for name in ("claude_code", "codex")
        })).model_dump(mode="json"),
        "tool": ToolConfigResponse(
            name="fixture-tool", display_name="Fixture tool", description="Contract fixture", category="file",
            config_specs=[ToolConfigSpecResponse(path="limit", type="integer", default=5)],
            current_values={"limit": 5},
        ).model_dump(mode="json"),
        "config": ConfigResponse(success=True, message="OK", data=config).model_dump(mode="json"),
        "failure": ConfigResponse(success=False, message="Configuration unavailable").model_dump(mode="json"),
        "onboardingStatus": OnboardingStatusResponse(
            success=True, message="OK", data=OnboardingStatusDataModel(completed=False),
        ).model_dump(mode="json"),
        "onboardingTemplate": OnboardingTemplateResponse(
            success=True, message="OK", data=OnboardingTemplateDataModel(config=config),
        ).model_dump(mode="json"),
    }


def build_plugin_contract() -> dict:
    from magi.api.routers.plugins import plugins_router
    from magi.api.routers.plugins_schemas import (
        PluginInstallCandidateResponse,
        PluginInstallJobSnapshot,
        PluginPackageResponse,
        PluginRegistryResponse,
        PluginSettingsActionRunResponse,
        PluginSettingsResourceResponse,
        PluginsListResponse,
    )
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    models = [PluginPackageResponse, PluginInstallCandidateResponse, PluginInstallJobSnapshot,
              PluginRegistryResponse, PluginSettingsActionRunResponse, PluginSettingsResourceResponse,
              PluginsListResponse]
    public = _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"])
    for model in models:
        if not any(route.response_model is model for route in public.routes):
            raise RuntimeError(f"Plugin contract is not exposed by the public router: {model.__name__}")
    _, document = models_json_schema(
        [(model, "serialization") for model in models],
        schema_generator=ResponseJsonSchema,
        ref_template="#/components/schemas/{model}",
    )
    return {
        "openapi": "3.1.0",
        "info": {"title": "Magi plugin response contracts", "version": "1"},
        "paths": {},
        "components": {"schemas": document["$defs"]},
    }


def build_plugin_examples() -> dict:
    from magi.api.routers.plugins_schemas import (
        ExtensionFieldResponse,
        PluginContributionResponse,
        PluginInstallJobSnapshot,
        PluginManifestResponse,
        PluginPackageResponse,
        PluginSettingsActionRunResponse,
        PluginsListResponse,
    )

    package = PluginPackageResponse(
        manifest=PluginManifestResponse(
            plugin_id="fixture-source", name="Fixture source", version="1.0.0",
            description="Contract fixture", author="Magi", official=False,
            contribution_types=["sensor"], source="local", plugin_dir="/fixture", manifest_path="/fixture/plugin.toml",
        ), enabled=True, trusted=True, loaded=True, healthy=True,
        contributions=[PluginContributionResponse(
            plugin_id="fixture-source", contribution_id="sensor", contribution_type="sensor",
            display_name="Source", description="", surface="timeline",
            fields=[ExtensionFieldResponse(key="enabled", type="switch", label="Enabled", default=True)],
        )], current_settings={"enabled": True},
    )
    return {
        "package": package.model_dump(mode="json"),
        "list": PluginsListResponse(plugins=[package], total=1).model_dump(mode="json"),
        "job": PluginInstallJobSnapshot(
            job_id="fixture-job", operation="install", plugin_id="fixture-source", status="completed",
            stage="completed", message="Installed", progress_pct=100, result=package,
            created_at_ms=1000, updated_at_ms=2000, finished_at_ms=2000,
        ).model_dump(mode="json"),
        "action": PluginSettingsActionRunResponse(
            plugin_id="fixture-source", action_id="connect", session_id="fixture-action", status="succeeded",
            message="Connected", settings_updates={"configured": True},
        ).model_dump(mode="json"),
    }


def build_event_contract() -> dict:
    from magi.agent.background.contracts import BackgroundTask, BackgroundTaskEvent
    from magi.chat.read.models import ChatDisplayMessage, ChatSessionSummary
    from magi.tools.code_agent.contracts import RunEvent

    models = [ChatDisplayMessage, ChatSessionSummary, BackgroundTask, BackgroundTaskEvent, RunEvent]
    _, definitions = ResponseJsonSchema(ref_template="#/components/schemas/{model}").generate_definitions([
        (model.__name__, "serialization", TypeAdapter(model).core_schema) for model in models
    ])
    return {
        "openapi": "3.1.0",
        "info": {"title": "Magi chat and task serialization contracts", "version": "1"},
        "paths": {}, "components": {"schemas": definitions},
    }


def build_event_examples() -> dict:
    from unittest.mock import patch

    from magi.agent.background.contracts import (
        BackgroundTask,
        BackgroundTaskSpec,
        BackgroundTaskStatus,
    )
    from magi.chat.read.models import ChatDisplayMessage, ChatSessionSummary
    from magi.runtime_trace import notification_payloads as notifications
    from magi.tools.code_agent.contracts import RunEvent

    message = ChatDisplayMessage(
        role="assistant", content="Hello", timestamp=1000, kind="assistant",
        message_id="fixture-message", message_kind="assistant_final", turn_id="fixture-turn",
    )
    session = ChatSessionSummary(
        session_id="fixture-session", title="Chat", last_message_preview="Hello",
        last_user_message_preview="Hi", title_overridden=False, last_timestamp=1000, message_count=2,
    )
    task = BackgroundTask(
        task_id="fixture-task", spec=BackgroundTaskSpec(
            user_id="fixture-user", session_id="fixture-session", origin_turn_id="fixture-turn",
            title="Task", goal="Inspect workspace", run_id="fixture-run",
        ), status=BackgroundTaskStatus.SUSPENDED_WAITING_USER, created_at=1.0, updated_at=1.0,
    )
    with patch.object(notifications.time, "time", return_value=1.0):
        return {
            "message": message.to_dict(), "session": session.to_dict(), "task": task.to_dict(),
            "runEvent": RunEvent(kind="status", ts_ms=1000, payload={"text": "Working"}).model_dump(mode="json"),
            "upsert": notifications.chat_message_upsert_payload(
                user_id="fixture-user", session_id=session.session_id, message_id=message.message_id,
                message=message, session_summary=session,
            ),
            "hidden": notifications.chat_message_hidden_payload(
                user_id="fixture-user", session_id=session.session_id, message_id=message.message_id,
                session_summary=session,
            ),
            "response": notifications.agent_response_payload(
                user_id="fixture-user", session_id=session.session_id, content="Hello",
                extra_fields={"turn_id": "fixture-turn", "message_id": message.message_id},
            ),
            "chunk": notifications.agent_response_chunk_payload(
                user_id="fixture-user", session_id=session.session_id, turn_id="fixture-turn",
                event={"kind": "text_delta", "text": "Hello"}, is_final=False, seq=1,
            ),
            "control": notifications.execution_control_payload(
                user_id="fixture-user", session_id=session.session_id, turn_id="fixture-turn",
                run_id="fixture-run", state="cancelling", can_cancel=False, label=None,
            ),
        }


def lifecycle_models_and_routes():
    from magi.api.routers.memory import memory_router
    from magi.api.routers.memory.clear import ClearMemoryResponseModel
    from magi.api.routers.memory.history_import_routes import (
        HistoryImportAppendResponse, HistoryImportJobResponse,
        HistoryImporterResponse, HistoryImportSourcePreviewResponse,
    )
    from magi.api.routers.memory.schemas import DeleteL1EventResponse, ForgetEntityResponse, ForgetEpisodeResponse
    from magi.api.routers.messages import user_messages_router
    from magi.api.routers.messages_models import ClearHistoryResponse, DeleteMessageResponse, DeleteSessionResponse
    from magi.memory.portability.operations import MemoryPortabilityOperation

    memory_routes = {
        ("POST", "/history-imports/markdown/preview"): HistoryImportJobResponse,
        ("POST", "/history-imports/{job_id}/markdown/append"): HistoryImportAppendResponse,
        ("GET", "/history-imports/importers"): list[HistoryImporterResponse],
        ("GET", "/history-imports/{job_id}/source-preview"): HistoryImportSourcePreviewResponse,
        ("GET", "/history-imports"): list[HistoryImportJobResponse],
        ("GET", "/history-imports/{job_id}"): HistoryImportJobResponse,
        ("PATCH", "/history-imports/{job_id}/selection"): HistoryImportJobResponse,
        ("POST", "/history-imports/{job_id}/confirm"): HistoryImportJobResponse,
        ("POST", "/history-imports/{job_id}/resume"): HistoryImportJobResponse,
        ("POST", "/portability/backups"): MemoryPortabilityOperation,
        ("POST", "/portability/exports"): MemoryPortabilityOperation,
        ("POST", "/portability/restores/inspect"): MemoryPortabilityOperation,
        ("POST", "/portability/restores/{candidate_id}/confirm"): MemoryPortabilityOperation,
        ("GET", "/portability/operations/{operation_id}"): MemoryPortabilityOperation,
        ("GET", "/portability/operations/active"): MemoryPortabilityOperation | None,
        ("GET", "/portability/operations/latest"): MemoryPortabilityOperation | None,
        ("DELETE", "/clear"): ClearMemoryResponseModel,
        ("DELETE", "/l1/events/{event_id}"): DeleteL1EventResponse,
        ("POST", "/forget/entity"): ForgetEntityResponse,
        ("POST", "/forget/time-range"): ForgetEntityResponse,
        ("POST", "/forget/episode"): ForgetEpisodeResponse,
    }
    message_routes = {
        ("POST", "/history/clear"): ClearHistoryResponse,
        ("DELETE", "/session/{session_id}/message/{message_id}"): DeleteMessageResponse,
        ("DELETE", "/session/{session_id}"): DeleteSessionResponse,
    }
    models = [HistoryImportAppendResponse, HistoryImportJobResponse, HistoryImporterResponse,
              HistoryImportSourcePreviewResponse, MemoryPortabilityOperation, ClearMemoryResponseModel,
              DeleteL1EventResponse, ForgetEntityResponse, ForgetEpisodeResponse,
              ClearHistoryResponse, DeleteMessageResponse, DeleteSessionResponse]
    return models, [("memory", memory_router, memory_routes), ("messages", user_messages_router, message_routes)]


def build_lifecycle_contract() -> dict:
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    models, groups = lifecycle_models_and_routes()
    for group, router, contracts in groups:
        public = _build_public_router(router, _PUBLIC_ROUTE_METHODS[group])
        for (method, path), model in contracts.items():
            route = next((route for route in public.routes if route.path == path and method in route.methods), None)
            if route is None or route.response_model != model:
                raise RuntimeError(f"Lifecycle response contract is not exposed: {method} {group}{path}")
            if route.response_model_exclude_none or route.response_model_exclude_unset or route.response_model_exclude_defaults:
                raise RuntimeError(f"Lifecycle response must serialize complete fields: {group}{path}")
    _, document = models_json_schema(
        [(model, "serialization") for model in models], schema_generator=ResponseJsonSchema,
        ref_template="#/components/schemas/{model}",
    )
    return {"openapi": "3.1.0", "info": {"title": "Magi data lifecycle response contracts", "version": "1"},
            "paths": {}, "components": {"schemas": document["$defs"]}}


def build_lifecycle_examples() -> dict:
    from magi.api.routers.memory.clear import ClearMemoryResponseModel, build_clear_memory_response
    from magi.api.routers.memory.history_import_routes import _response, HistoryImportAppendResponse, HistoryImporterResponse, HistoryImportSourcePreviewResponse
    from magi.api.routers.memory.schemas import DeleteL1EventResponse, ForgetEntityResponse, ForgetEpisodeResponse
    from magi.api.routers.messages_models import ClearHistoryResponse, DeleteMessageResponse, DeleteSessionResponse
    from magi.memory.history_imports.models import HistoryImportJob, HistoryImportParticipant, HistoryImportSourceSummary
    from magi.memory.portability.operations import MemoryPortabilityOperation, ReadyMemoryRestoreInspection

    job = _response(HistoryImportJob(
        job_id="fixture-import", source_type="markdown", source_fingerprint="fixture-fingerprint",
        source_ids=["fixture-source"], included_source_ids=["fixture-source"], detected_kind="document",
        status="preview_ready", total_records=1, meaningful_records=1, quick_target_records=1, quick_max_records=10,
        quick_imported_count=0, imported_count=0, projected_count=0, self_participant_ids=[], warnings=[],
        quick_ready=False, created_at=1.0, updated_at=1.0,
        participants=[HistoryImportParticipant("document_author", "Author", 1, 1, "A note")],
        sources=[HistoryImportSourceSummary("fixture-source", "note.md", "document", 1, 1, 1.0, 1.0, "exact", "A note", True)],
    ))
    operation = MemoryPortabilityOperation(operation_id="fixture-export", kind="export", created_at="2026-09-05T00:00:00Z")
    inspection = ReadyMemoryRestoreInspection(
        state="ready", candidate_id="fixture-candidate", encrypted=False, format_version=1, magi_version="0.1.29",
        created_at="2026-09-05T00:00:00Z", scope=["l1"], record_counts={"l1": 1}, compatibility="compatible",
        warnings=[], expires_at="2026-09-05T01:00:00Z", source_fingerprint="fixture-fingerprint",
    )
    return {
        "importJob": job.model_dump(mode="json"),
        "sourcePreview": HistoryImportSourcePreviewResponse(source_id="fixture-source", source_name="note.md", detected_kind="document", records=[], truncated=False).model_dump(mode="json"),
        "importAppend": HistoryImportAppendResponse(job=job, added_source_count=1, duplicate_source_count=0).model_dump(mode="json"),
        "importer": HistoryImporterResponse(plugin_id="fixture-plugin", importer_id="history", display_name="History",
            display_name_i18n={}, description="Import history", description_i18n={}, accepted_extensions=[".json"],
            participant_identity_scope="source", export_help_url=None).model_dump(mode="json"),
        "operation": operation.model_dump(mode="json"),
        "completedExport": operation.model_copy(update={"status": "succeeded", "phase": "completed", "progress_percent": 100.0,
            "output_path": "/fixture/export.zip", "file_size_bytes": 42, "completed_at": "2026-09-05T00:01:00Z"}).model_dump(mode="json"),
        "inspection": MemoryPortabilityOperation(operation_id="fixture-inspect", kind="inspect", status="succeeded",
            created_at="2026-09-05T00:00:00Z", inspection=inspection).model_dump(mode="json"),
        "clearMemory": ClearMemoryResponseModel.model_validate(build_clear_memory_response(
            l0_count=1, l1_count=2, l2_count=3, l3_count=0, l4_count=0, chat_context_count=1)).model_dump(mode="json"),
        "deleteEvent": DeleteL1EventResponse(event_id="fixture-event", deleted=True, deletion_scope="source_event").model_dump(mode="json"),
        "forgetEntity": ForgetEntityResponse(l2_counts={"entities": 1}, l1_events_deleted=1).model_dump(mode="json"),
        "forgetEpisode": ForgetEpisodeResponse(episode_id="fixture-episode", event_ids=["fixture-event"], l1_events_deleted=1).model_dump(mode="json"),
        "clearHistory": ClearHistoryResponse(success=True, message="Cleared", user_id="fixture-user", session_id="fixture-session",
            cleared_message_ids=["fixture-message"], cleared_turn_ids=["fixture-turn"]).model_dump(mode="json"),
        "deleteMessage": DeleteMessageResponse(success=True, user_id="fixture-user", session_id="fixture-session",
            deleted_message_id="fixture-message").model_dump(mode="json"),
        "deleteSession": DeleteSessionResponse(success=True, user_id="fixture-user", deleted_session_id="fixture-session").model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Router imports initialize logging. Contract generation must never touch user data.
    from magi.utils.runtime import set_runtime_dir

    with tempfile.TemporaryDirectory(prefix="magi-contract-export-") as runtime_dir:
        set_runtime_dir(runtime_dir)
        outputs = {
            "frontend-lifecycle.json": build_lifecycle_contract(), "frontend-lifecycle-examples.json": build_lifecycle_examples(),
            "frontend-config.json": build_contract(), "frontend-config-examples.json": build_examples(),
            "frontend-plugins.json": build_plugin_contract(), "frontend-plugins-examples.json": build_plugin_examples(),
            "frontend-events.json": build_event_contract(), "frontend-events-examples.json": build_event_examples(),
        }
    for name, payload in outputs.items():
        target = ROOT / "contracts" / "api" / name
        content = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                print(f"{name} is stale; run scripts/export-frontend-contracts.py", file=sys.stderr)
                return 1
        else:
            target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
