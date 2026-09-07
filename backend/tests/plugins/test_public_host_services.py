"""Public RPC bounds, original caller binding and revocable installed consent."""

from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from magi_plugin_sdk.capabilities import (
    AskUserRequest,
    AskUserResult,
    HOST_METHODS,
    MemorySearchRequest,
)
from magi_plugin_sdk.contracts import PluginCapability
from magi_plugin_sdk.host_services import RemoteHostServices, validate_host_payload
from magi_plugin_sdk.runtime import CapabilityReadiness, OperationSpec, PluginConnection
from magi_plugin_sdk.tools import ToolExecutionContext as PublicContext
from magi_plugin_sdk.transport import ProtocolError, pack, read_frame
from magi.bootstrap.tool_capabilities import _HostMemoryQueryPort
from magi.core.tool_capabilities import AskOutcome, ToolCapabilities
from magi.core.tool_context import ToolExecutionContext
from magi.memory.hybrid_retrieval.models import RetrievalPayload
from magi.plugins.host_services import dispatch_host_service, permitted_host_methods, public_context
from magi.plugins.operation_authorization import InstalledOperationAuthorizer, build_host_invocation
from magi.plugins.process_broker import CapabilityDenied


def context(**updates):
    connection = PluginConnection(
        connection_id="conn", plugin_id="example", display_name="Example", enabled=True
    )
    values = dict(
        agent_id="chat",
        connection=connection,
        invocation=build_host_invocation(connection, trigger="model", session_id="session"),
        env_vars={"user_id": "local_user", "session_id": "session", "turn_id": "turn"},
        capabilities=ToolCapabilities(),
        host_service_grants=frozenset(HOST_METHODS),
        host_service_authorize=lambda _: True,
    )
    return ToolExecutionContext(**{**values, **updates})


def memory_port():
    port = _HostMemoryQueryPort()
    port._service = SimpleNamespace(
        query=AsyncMock(
            return_value=RetrievalPayload(
                l1_events=[
                    {
                        "event_id": "event",
                        "content": "The user said: only on Fridays.",
                        "timestamp": 1720000000.0,
                        "score": 0.9,
                        "metadata": {"private_path": "/host/private/data"},
                    }
                ],
                trace={"private_path": "/host/private/memory.db"},
            )
        )
    )
    return port


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "hello", "user_id": "victim"},
        {"query": "hello", "session_id": "victim"},
        {"query": "hello", "turn_id": "victim"},
        {"query": "hello", "query_mode": "graph"},
        {"query": "hello", "limit": True},
        {"query": "hello", "limit": 11},
        {"query": "hello", "limit": 0},
        {"query": " "},
        {"query": "x" * 2001},
    ],
)
@pytest.mark.asyncio
async def test_memory_cannot_select_authority_or_exceed_bounds(payload):
    port = memory_port()
    with pytest.raises(ValidationError):
        await dispatch_host_service(
            context(capabilities=ToolCapabilities(memory_query=port)), "memory.search", payload
        )
    port._service.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_uses_real_host_query_and_governed_projection():
    port = memory_port()
    ctx = context(capabilities=ToolCapabilities(memory_query=port))
    ctx.env_vars["current_user_text"] = "What was my condition?"
    seen = []

    async def callback(kind, payload):
        seen.append((kind, payload))
        return await dispatch_host_service(ctx, payload["method"], payload["request"])

    result = await RemoteHostServices(callback, permitted_host_methods(ctx)).memory_search(
        MemorySearchRequest(query="Fridays", limit=1)
    )
    assert result.status == "found"
    assert result.findings[0].statement == "The user said: only on Fridays."
    query = port._service.query.await_args.args[0]
    assert (query.user_id, query.session_id, query.limit) == ("local_user", "session", 1)
    assert query.exclude_user_text == "What was my condition?"
    assert seen == [
        ("host_service", {"method": "memory.search", "request": {"query": "Fridays", "limit": 1}})
    ]
    assert "/host/private" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_empty_memory_is_honest_not_found():
    port = memory_port()
    port._service.query.return_value = RetrievalPayload()
    result = await dispatch_host_service(
        context(capabilities=ToolCapabilities(memory_query=port)),
        "memory.search",
        {"query": "nothing"},
    )
    assert result["status"] == "not_found" and result["insufficient_evidence"] is True
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_memory_preserves_semantics_and_marks_clipping():
    port = memory_port()
    port.project_historical_recall = lambda **_: SimpleNamespace(
        status="conflicted",
        summary="summary",
        insufficient_evidence=False,
        findings=[
            dict(
                statement="x" * 2200,
                kind="event",
                source_layer="L1",
                status="active",
                evidence_semantics="historical_record",
                correction_status="corrected",
            )
            for _ in range(3)
        ],
    )
    result = await dispatch_host_service(
        context(capabilities=ToolCapabilities(memory_query=port)),
        "memory.search",
        {"query": "x", "limit": 2},
    )
    assert len(result["findings"]) == 2 and result["truncated"] is True
    assert result["findings"][0]["truncated"] is True
    assert result["findings"][0]["correction_status"] == "corrected"
    assert result["status"] == "conflicted"


def test_public_context_has_no_internal_objects_or_grants():
    ctx = context(cancellation=asyncio.Event(), trace_context=object(), progress=lambda _: None)
    ctx.env_vars["SECRET"] = "secret"
    public = public_context(ctx)
    assert type(public) is PublicContext
    assert public.host is None and public.progress is None and public.env_vars == {}
    assert not {
        "capabilities",
        "cancellation",
        "trace_context",
        "host_service_grants",
        "host_service_authorize",
    } & set(PublicContext.model_fields)
    assert read_frame(BytesIO(pack({"context": public})))["context"] == public
    with pytest.raises(ProtocolError):
        pack({"context": ctx})
    with pytest.raises(ValidationError):
        PublicContext(agent_id="a", capabilities=ToolCapabilities())


@pytest.mark.parametrize(
    "change",
    [
        {"host_service_grants": frozenset()},
        {"host_service_authorize": None},
        {"host_service_authorize": lambda _: False},
        {"invocation": None},
        {"connection": None},
        {"capabilities": None},
        {"env_vars": {"user_id": "victim", "session_id": "session", "turn_id": "turn"}},
        {"env_vars": {"user_id": "local_user", "session_id": "other", "turn_id": "turn"}},
        {"env_vars": {"user_id": "local_user", "session_id": "session"}},
    ],
)
@pytest.mark.asyncio
async def test_default_deny_requires_original_context_and_explicit_grant(change):
    ctx = context(**{"capabilities": ToolCapabilities(memory_query=memory_port()), **change})
    assert permitted_host_methods(ctx) == ()
    with pytest.raises(CapabilityDenied):
        await dispatch_host_service(ctx, "memory.search", {"query": "x"})


@pytest.mark.asyncio
async def test_modified_public_context_cannot_grant_itself_authority():
    public = public_context(context()).model_copy(
        update={
            "host_service_grants": frozenset(HOST_METHODS),
            "host_service_authorize": lambda _: True,
            "capabilities": ToolCapabilities(memory_query=memory_port()),
        }
    )
    assert permitted_host_methods(public) == ()
    with pytest.raises(CapabilityDenied):
        await dispatch_host_service(public, "memory.search", {"query": "x"})


@pytest.mark.asyncio
async def test_unknown_internal_method_is_never_dispatched():
    port = memory_port()
    with pytest.raises(CapabilityDenied):
        await dispatch_host_service(
            context(capabilities=ToolCapabilities(memory_query=port)), "memory.query", {}
        )
    port._service.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_during_memory_io_discards_private_result():
    port = memory_port()
    granted = True

    async def query(_):
        nonlocal granted
        granted = False
        return RetrievalPayload()

    port._service.query.side_effect = query
    ctx = context(
        capabilities=ToolCapabilities(memory_query=port), host_service_authorize=lambda _: granted
    )
    with pytest.raises(CapabilityDenied, match="revoked"):
        await dispatch_host_service(ctx, "memory.search", {"query": "x"})


@pytest.mark.parametrize("resolution", ["user", "cancelled", "timeout"])
@pytest.mark.asyncio
async def test_ask_uses_original_identity_and_returns_typed_outcome(resolution):
    ask = AsyncMock(
        return_value=AskOutcome(
            resolution == "user",
            "Yes" if resolution == "user" else None,
            resolution,
            resolution == "timeout",
        )
    )
    ctx = context(
        capabilities=ToolCapabilities(interaction=SimpleNamespace(ask=ask)),
        cancellation=asyncio.Event(),
    )
    result = await dispatch_host_service(
        ctx,
        "interaction.ask",
        {"question": "Continue?", "options": ["Yes", "No"], "timeout_seconds": 10.0},
    )
    assert AskUserResult.model_validate(result).resolution == resolution
    kwargs = ask.await_args.kwargs
    assert (kwargs["user_id"], kwargs["session_id"], kwargs["turn_id"]) == (
        "local_user",
        "session",
        "turn",
    )
    assert kwargs["cancellation"] is ctx.cancellation and kwargs["background"] is False


@pytest.mark.asyncio
async def test_background_ask_default_deny_and_explicit_permission(monkeypatch):
    monkeypatch.setattr("magi.plugins.host_services.get_user_preference", lambda *_: False)
    ask = AsyncMock(return_value=AskOutcome(True, "Yes", "user", False))
    background_port = object()
    ctx = context(
        agent_id="background:task",
        capabilities=ToolCapabilities(
            interaction=SimpleNamespace(ask=ask), background=background_port
        ),
    )
    assert "interaction.ask" not in permitted_host_methods(ctx)
    ctx.enabled_features.append("allow_ask_in_background")
    await dispatch_host_service(ctx, "interaction.ask", {"question": "Continue?"})
    assert ask.await_args.kwargs["background_task_id"] == "task"
    assert ask.await_args.kwargs["background_port"] is background_port


@pytest.mark.asyncio
async def test_cancelled_invocation_never_opens_ask():
    ask, token = AsyncMock(), asyncio.Event()
    token.set()
    ctx = context(
        capabilities=ToolCapabilities(interaction=SimpleNamespace(ask=ask)), cancellation=token
    )
    with pytest.raises(CapabilityDenied, match="cancelled"):
        await dispatch_host_service(ctx, "interaction.ask", {"question": "Continue?"})
    ask.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "Continue?", "user_id": "victim"},
        {"question": "Continue?", "background": False},
        {"question": "Continue?", "timeout_seconds": float("nan")},
        {"question": "Continue?", "timeout_seconds": 301},
        {"question": "Continue?", "options": ["x"] * 7},
        {"question": "Continue?", "allow_free_text": False},
    ],
)
def test_ask_rejects_authority_and_unbounded_or_unanswerable_requests(payload):
    with pytest.raises(ValueError):
        AskUserRequest.model_validate(payload)


@pytest.mark.parametrize(
    "value",
    [object(), {"x": object()}, {"x": float("nan")}, {"x": "x" * (129 * 1024)}, {"x": [0] * 513}],
)
def test_payload_rejects_host_objects_and_unbounded_values(value):
    with pytest.raises(ValueError):
        validate_host_payload(value)


@pytest.mark.asyncio
async def test_sdk_denies_ungranted_calls_and_checks_responses():
    callback = AsyncMock()
    with pytest.raises(PermissionError):
        await RemoteHostServices(callback).memory_search(MemorySearchRequest(query="x"))
    callback.assert_not_awaited()
    callback.return_value = {
        "answered": True,
        "answer": "yes",
        "resolution": "timeout",
        "timed_out": True,
    }
    with pytest.raises(ValidationError):
        await RemoteHostServices(callback, ("interaction.ask",)).ask_user(
            AskUserRequest(question="Continue?")
        )


def installed_authority(mode="restricted_process"):
    ctx = context()
    declaration = PluginCapability(
        capability="memory_search", scope=["current_user"], optional=True
    )
    configured = SimpleNamespace(trusted=True, consented_capabilities=[declaration])
    manifest = SimpleNamespace(source="installed", execution_mode=mode, capabilities=[declaration])
    state = SimpleNamespace(trusted=True, manifest=manifest)
    store = SimpleNamespace(
        get=lambda _: ctx.connection,
        get_readiness=lambda _: [
            CapabilityReadiness(connection_id="conn", capability_id="connection", status="ready")
        ],
    )
    authorizer = InstalledOperationAuthorizer(
        get_package=lambda _: state,
        connection_store=store,
        get_connection_plugin=lambda _: object(),
        config_provider=lambda: SimpleNamespace(
            plugins=SimpleNamespace(packages={"example": configured})
        ),
    )
    spec = OperationSpec(
        operation_id="find",
        description="Find",
        input_schema={"type": "object"},
        output_schema={},
        triggers=["model"],
        effect="read_only",
        replay="read_only",
    )
    return ctx, configured, manifest, authorizer, spec


@pytest.mark.parametrize("mode", ["restricted_process", "trusted_process"])
def test_installed_consent_is_required_and_revocable_for_host_methods(mode):
    ctx, config, manifest, auth, spec = installed_authority(mode)
    args = (ctx.invocation, ctx.connection, spec, {})
    assert auth(*args) and auth.authorize_host_service(*args, "memory.search")
    config.consented_capabilities = []
    assert auth(*args)  # Optional access does not revoke the ordinary tool.
    assert not auth.authorize_host_service(*args, "memory.search")
    config.consented_capabilities, manifest.capabilities = list(manifest.capabilities), []
    assert not auth.authorize_host_service(*args, "memory.search")


def test_ask_consent_cannot_override_read_only_effect_policy():
    ctx, config, manifest, auth, spec = installed_authority()
    manifest.capabilities = [
        PluginCapability(capability="interaction_ask", scope=["current_session"])
    ]
    config.consented_capabilities = list(manifest.capabilities)
    assert not auth.authorize_host_service(
        ctx.invocation, ctx.connection, spec, {}, "interaction.ask"
    )
    spec = spec.model_copy(update={"effect": "external_write", "replay": "non_idempotent"})
    assert auth.authorize_host_service(ctx.invocation, ctx.connection, spec, {}, "interaction.ask")


@pytest.mark.parametrize(
    "name,scope",
    [
        ("memory_search", []),
        ("memory_search", ["*"]),
        ("interaction_ask", ["current_user"]),
        ("memory_search", ["current_user", "other"]),
    ],
)
def test_manifest_requires_exact_host_service_scope(name, scope):
    with pytest.raises(ValidationError):
        PluginCapability(capability=name, scope=scope)


@pytest.mark.parametrize("consented", [False, True])
@pytest.mark.asyncio
async def test_operation_registry_mints_only_consented_tool_lease_and_revokes_it(
    runtime_paths_with_schema, consented
):
    from magi_plugin_sdk.tools import Tool, ToolResult, ToolSchema
    from magi.agent.background import BackgroundTaskStore
    from magi.plugins.operations import PluginOperationRegistry
    from magi.tools.registry import ToolRegistry

    ctx, config, _, auth, _ = installed_authority()
    if not consented:
        config.consented_capabilities = []
    port = memory_port()
    ctx.capabilities = ToolCapabilities(memory_query=port)
    captured = []

    class Probe(Tool):
        def _init_schema(self):
            self.schema = ToolSchema(
                name="probe",
                category="test",
                description="Read host memory",
                effect_class="read_only",
                effect_replay_policy="read_only",
            )

        async def execute(self, parameters, context):
            captured.append(context)
            methods = permitted_host_methods(context)
            if "memory.search" in methods:
                await dispatch_host_service(context, "memory.search", {"query": "Fridays"})
            return ToolResult(success=True, data={"methods": list(methods)})

    tools = ToolRegistry()
    tools.bind_tool_effect_ledger(
        BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    )
    registry = PluginOperationRegistry(
        tools, get_connection=lambda _: ctx.connection, authorize=auth
    )
    registry.register_tool(plugin_id="example", connection_id="conn", tool_class=Probe)
    result = await registry.invoke("conn", "probe", {}, identity=ctx.invocation, context=ctx)
    assert result.status == "succeeded"
    assert result.value == {"methods": ["memory.search"] if consented else []}
    assert port._service.query.await_count == int(consented)
    assert len(captured) == 1
    assert permitted_host_methods(captured[0]) == ()
    with pytest.raises(CapabilityDenied):
        await dispatch_host_service(captured[0], "memory.search", {"query": "after completion"})


@pytest.mark.asyncio
async def test_memory_byte_budget_handles_json_escaping():
    port = memory_port()
    port.project_historical_recall = lambda **_: SimpleNamespace(
        status="found",
        summary="summary",
        insufficient_evidence=False,
        findings=[
            dict(
                statement="\x00" * 2000,
                evidence_text="\x01" * 2000,
                kind="event",
                source_layer="L1",
            )
            for _ in range(10)
        ],
    )
    result = await dispatch_host_service(
        context(capabilities=ToolCapabilities(memory_query=port)),
        "memory.search",
        {"query": "x", "limit": 10},
    )
    assert 0 < len(result["findings"]) < 10
    assert result["truncated"] is True
    validate_host_payload(result)


def test_optional_host_service_readiness_failure_is_denied():
    ctx, _, _, auth, spec = installed_authority()
    auth._readiness = lambda _: [
        CapabilityReadiness(connection_id="conn", capability_id="connection", status="ready"),
        CapabilityReadiness(
            connection_id="conn", capability_id="memory_search", status="failed"
        ),
    ]
    assert not auth.authorize_host_service(
        ctx.invocation, ctx.connection, spec, {}, "memory.search"
    )
