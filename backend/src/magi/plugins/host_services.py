"""Public host services admitted only under a live, original tool invocation.

The worker sends a method and strict JSON request. Services and principal,
session, turn, cancellation and background authority remain in the host.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Protocol, runtime_checkable

from magi_plugin_sdk.capabilities import (
    AskUserRequest,
    AskUserResult,
    HOST_METHODS,
    HostMethod,
    MemoryFinding,
    MemorySearchRequest,
    MemorySearchResult,
)
from magi_plugin_sdk.host_services import MAX_HOST_SERVICE_BYTES, validate_host_payload
from magi_plugin_sdk.runtime import InvocationIdentity, OperationSpec, PluginConnection
from magi_plugin_sdk.tools import ToolExecutionContext as PublicToolExecutionContext

from ..config import get_user_preference
from ..identity import CANONICAL_LOCAL_USER
from .process_broker import CapabilityDenied
from ..core.tool_context import ToolExecutionContext


@runtime_checkable
class HostServiceAuthorizer(Protocol):
    def authorize_host_service(
        self,
        identity: InvocationIdentity,
        connection: PluginConnection,
        spec: OperationSpec,
        parameters: dict[str, Any],
        method: HostMethod,
    ) -> bool: ...


def public_context(context: PublicToolExecutionContext) -> PublicToolExecutionContext:
    """Project an exact SDK value; never serialize a host subtype or live handles."""
    return PublicToolExecutionContext(
        agent_id=context.agent_id,
        invocation=context.invocation,
        connection=context.connection,
        task_id=context.task_id,
        workspace=context.workspace,
        permissions=list(context.permissions),
        enabled_features=list(context.enabled_features),
    )


def _has_authority(context: PublicToolExecutionContext) -> bool:
    if not isinstance(context, ToolExecutionContext):
        return False
    identity, connection = context.invocation, context.connection
    return bool(
        identity is not None
        and connection is not None
        and connection.enabled
        and identity.plugin_id == connection.plugin_id
        and identity.connection_id == connection.connection_id
        and identity.principal_id == str(CANONICAL_LOCAL_USER)
        and context.env_vars.get("user_id") == identity.principal_id
        and identity.session_id
        and context.env_vars.get("session_id") == identity.session_id
        and context.env_vars.get("turn_id")
        and context.capabilities is not None
        and context.host_service_authorize is not None
    )


def _background(context: ToolExecutionContext) -> bool:
    return context.agent_id.startswith("background:") or context.env_vars.get(
        "intent", ""
    ).startswith("background")


def _ask_allowed(context: ToolExecutionContext) -> bool:
    if context.invocation.trigger not in {"user", "model"}:
        return False
    if not _background(context):
        return True
    return (
        "allow_ask_in_background" in context.enabled_features
        or get_user_preference("allow_ask_in_background", False) is True
    )


def permitted_host_methods(context: PublicToolExecutionContext) -> tuple[HostMethod, ...]:
    """Return a discovery hint from injected ports and current, explicit grants."""
    if not _has_authority(context):
        return ()
    methods: list[HostMethod] = []
    for method in HOST_METHODS:
        if method not in context.host_service_grants:
            continue
        if method == "memory.search" and context.capabilities.memory_query is None:
            continue
        if method == "interaction.ask" and (
            context.capabilities.interaction is None or not _ask_allowed(context)
        ):
            continue
        if context.host_service_authorize(method) is True:
            methods.append(method)
    return tuple(methods)


async def _check_cancelled(context: ToolExecutionContext) -> None:
    token = context.cancellation
    if token is None:
        return
    if isinstance(token, asyncio.Event):
        cancelled = token.is_set()
    else:
        cancelled = token.is_cancelled()
        if inspect.isawaitable(cancelled):
            cancelled = await cancelled
    if cancelled:
        raise CapabilityDenied("Host service invocation was cancelled")


async def dispatch_host_service(
    context: PublicToolExecutionContext,
    method: str,
    request: object,
) -> dict[str, Any]:
    """Dispatch an allowlisted request; callbacks cannot supply authority fields."""
    if method not in permitted_host_methods(context):
        raise CapabilityDenied("Host method was not granted to this invocation")
    validate_host_payload(request)
    await _check_cancelled(context)
    if method == "memory.search":
        query = MemorySearchRequest.model_validate(request)
        result = await asyncio.wait_for(_memory_search(context, query), timeout=30.0)
    elif method == "interaction.ask":
        question = AskUserRequest.model_validate(request)
        result = await asyncio.wait_for(
            _ask_user(context, question), timeout=question.timeout_seconds + 1.0
        )
    else:
        raise CapabilityDenied("Unknown public host method")
    # Revocation/cancellation while awaiting I/O cannot release private results.
    if method not in permitted_host_methods(context):
        raise CapabilityDenied("Host service authority was revoked")
    await _check_cancelled(context)
    response = result.model_dump(mode="json")
    validate_host_payload(response)
    return response


async def _memory_search(
    context: ToolExecutionContext, request: MemorySearchRequest
) -> MemorySearchResult:
    port = context.capabilities.memory_query
    query = port.build_query(
        query=request.query,
        user_id=context.invocation.principal_id,
        session_id=context.invocation.session_id,
        limit=request.limit,
        exclude_user_text=context.env_vars.get("current_user_text"),
        context_signals={
            "workspace_path": context.env_vars.get("memory_context_workspace"),
            "user_text": context.env_vars.get("current_user_text") or request.query,
            "task_category": context.env_vars.get("intent", ""),
        },
    )
    payload = await port.query(query)
    entity_ids: set[str] = set()
    for records, keys in (
        (payload.l2_relationships, ("subject_id", "object_id")),
        (payload.l2_assertions, ("entity_id", "target_entity_id")),
        (payload.l2_entity_cards, ("entity_id",)),
    ):
        for record in records:
            for key in keys:
                value = record.get(key)
                if isinstance(value, str) and value:
                    entity_ids.add(value)
    names = await port.get_canonical_names(entity_ids) if entity_ids else {}
    recall = port.project_historical_recall(payload=payload, request=query, canonical_names=names)
    findings: list[MemoryFinding] = []
    truncated = len(recall.findings) > request.limit or len(recall.summary) > 2000
    for raw in recall.findings[: request.limit]:
        statement = raw["statement"]
        evidence = raw.get("evidence_text")
        clipped = len(statement) > 2000 or (evidence is not None and len(evidence) > 2000)
        findings.append(
            MemoryFinding.model_validate(
                {
                    "statement": statement[:2000],
                    "source_layer": raw["source_layer"],
                    "kind": raw["kind"],
                    "occurred_at": raw.get("occurred_at"),
                    "status": raw.get("status"),
                    "evidence_semantics": raw.get("evidence_semantics"),
                    "correction_status": raw.get("correction_status"),
                    "evidence_text": evidence[:2000] if evidence is not None else None,
                    "truncated": clipped,
                }
            )
        )
        truncated = truncated or clipped
    result = MemorySearchResult.model_validate(
        {
            "status": recall.status,
            "summary": recall.summary[:2000],
            "findings": [item.model_dump(mode="json") for item in findings],
            "insufficient_evidence": recall.insufficient_evidence,
            "truncated": truncated,
        }
    )
    # The byte budget also covers multibyte text and JSON escape expansion.
    while (
        len(json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))
        > MAX_HOST_SERVICE_BYTES
    ):
        result = result.model_copy(update={"findings": result.findings[:-1], "truncated": True})
    return result


async def _ask_user(context: ToolExecutionContext, request: AskUserRequest) -> AskUserResult:
    background = _background(context)
    task_id = (
        context.agent_id.removeprefix("background:")
        if context.agent_id.startswith("background:")
        else None
    )
    outcome = await context.capabilities.interaction.ask(
        session_id=context.invocation.session_id,
        user_id=context.invocation.principal_id,
        turn_id=context.env_vars["turn_id"],
        question=request.question,
        options=list(request.options),
        allow_free_text=request.allow_free_text,
        timeout_seconds=request.timeout_seconds,
        background=background,
        background_task_id=task_id if background else None,
        background_port=context.capabilities.background if background else None,
        cancellation=context.cancellation,
    )
    return AskUserResult.model_validate(
        {
            "answered": outcome.answered,
            "answer": outcome.answer,
            "resolution": outcome.resolution,
            "timed_out": outcome.timed_out,
        }
    )


__all__ = [
    "HostServiceAuthorizer",
    "public_context",
    "permitted_host_methods",
    "dispatch_host_service",
]
