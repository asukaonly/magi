"""Keep chat application effects local while repository transactions run in a plugin."""

from __future__ import annotations

import inspect
import json
import logging
from contextlib import asynccontextmanager
from contextvars import copy_context
from typing import Any, Callable, Protocol, get_type_hints

from pydantic import ConfigDict, TypeAdapter, create_model
from magi_plugin_sdk.storage import StorageCall, StorageResult
from magi_plugin_sdk.storage_errors import DOMAIN_ERRORS, domain_failure, raise_domain_failure
from magi_plugin_sdk.storage_chat.host import ChatStorageHost
from magi_plugin_sdk.storage_chat.remote_host import HOST_METHODS
from magi_plugin_sdk.storage_ports.chat import ChatRepository
from magi_plugin_sdk.storage_ports.chat_reads import ChatStorageReads

from ...core.chat_assets.mutations import chat_asset_mutation
from ...core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError
from ..asset_validation import has_explicit_asset_payload_map, has_managed_asset_payloads
from ..workspace_preferences import RecentWorkspaceRepository
from .host import LocalChatStorageHost

logger = logging.getLogger(__name__)
HostHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


class ChatStorageTransport(Protocol):
    async def invoke_with_host(self, request: StorageCall, handler: HostHandler) -> StorageResult: ...
    def invoke_sync_with_host(self, request: StorageCall, handler: HostHandler) -> StorageResult: ...


class ScopedChatHost:
    """No callback may expand the user, session, payload or workspace of its request."""

    def __init__(self, host: LocalChatStorageHost, request: StorageCall) -> None:
        self.host, self.request = host, request
        self.context = copy_context()

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.context.copy().run(self._call, name, arguments)

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in HOST_METHODS:
            raise PermissionError("Unknown chat storage host operation")
        self._authorize(name, arguments)
        prototype = getattr(ChatStorageHost, name)
        hints = get_type_hints(prototype)
        fields = {key: (hints[key], ... if value.default is value.empty else value.default)
                  for key, value in inspect.signature(prototype).parameters.items() if key != "self"}
        model = create_model(name, __config__=ConfigDict(extra="forbid"), **fields)
        values = model.model_validate_json(json.dumps(arguments), strict=True)
        try:
            result = getattr(self.host, name)(**{key: getattr(values, key) for key in fields})
            result_type = TypeAdapter(hints["return"])
            reply = StorageResult(value=result_type.dump_python(result_type.validate_python(result), mode="json"))
        except tuple(DOMAIN_ERRORS.values()) as exc:
            reply = domain_failure(exc)
        return reply.model_dump(mode="json")

    def _authorize(self, name: str, values: dict[str, Any]) -> None:
        args, operation = self.request.arguments, self.request.operation
        if name == "prepare_assets" and self.request.repository == "chat":
            message = values.get("message")
            if not isinstance(message, dict):
                raise PermissionError("Attachment context requires a message")
            expected = args.get("record")
            payloads = args.get("attachment_payloads")
            if operation in {"commit_user_turn_assistant_outcome", "commit_unmanaged_assistant_outcome"}:
                expected = next((item for item in args.get("messages", [])
                                 if item.get("message_id") == message.get("message_id")), None)
                payloads = args.get("attachment_payloads_by_message_id", {}).get(message.get("message_id"))
            elif operation in {"create_user_turn", "create_user_turn_once"}:
                expected = args
            elif operation != "append_message":
                expected = None
            if (not isinstance(expected, dict)
                or any(message.get(key) != expected.get(key) for key in ("user_id", "session_id", "turn_id"))
                or values.get("payloads") != payloads):
                raise PermissionError("Attachment request exceeds the original write")
            return
        if name == "claim_workspace_identity":
            if operation in {"create_user_turn", "create_user_turn_once"}:
                expected = (args.get("runtime_envelope") or {}).get("workspace_path")
            elif operation in {"create_new_session", "acreate_new_session", "update_session_workspace", "aupdate_session_workspace"}:
                expected = args.get("workspace_path")
            else:
                raise PermissionError("This operation cannot claim a workspace")
            if (str(expected or "").strip() or None) != values.get("path"):
                raise PermissionError("Workspace request exceeds the original write")
            return
        if self.request.repository != "reads":
            raise PermissionError("Host reads require a chat read invocation")
        if name == "list_snapshot_asset_references":
            if operation not in {"prepare_session_cleanup", "prepare_history_cleanup", "prepare_message_cleanup"}:
                raise PermissionError("Asset inventory requires a cleanup request")
            if values.get("session_id") != args.get("session_id"):
                raise PermissionError("Asset inventory exceeds the cleanup session")
            return
        if name in {"get_read_revision", "get_trace_summary", "get_turn_activity_map"}:
            if operation not in {"get_history_page", "aget_history_page", "get_display_history", "aget_display_history", "get_display_message", "aget_display_message"}:
                raise PermissionError("Trace enrichment requires a history query")
            if any(values.get(key) != args.get(key) for key in ("user_id", "session_id")):
                raise PermissionError("Trace query exceeds the original session")
            return
        raise PermissionError("Storage host operation is not authorized")


class ChatStorageProxy:
    def __init__(self, transport: ChatStorageTransport, session_id: str, *, repository: str,
                 host: LocalChatStorageHost, workspace_preferences: RecentWorkspaceRepository | None = None) -> None:
        self.transport, self.session_id, self.repository = transport, session_id, repository
        self.host = host
        self.workspace_preferences = workspace_preferences
        self._waker: Callable[[], None] | None = None
        contract = ChatRepository if repository == "chat" else ChatStorageReads
        self.methods = {name: function for base in reversed(contract.__mro__) for name, function in vars(base).items()
                        if not name.startswith("_") and inspect.isfunction(function)}

    def set_assistant_memory_outbox_waker(self, waker: Callable[[], None] | None) -> None:
        self._waker = waker

    def fork(self) -> ChatStorageProxy:
        # The worker opens an isolated connection for every read invocation.
        return self

    def close(self) -> None:
        # The selected provider owns the session until all consumers stop.
        pass

    def __getattr__(self, name: str) -> Any:
        prototype = self.methods.get(name)
        if prototype is None:
            raise AttributeError(name)
        signature, hints = inspect.signature(prototype), get_type_hints(prototype)
        result_type = TypeAdapter(hints["return"])

        def request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> StorageCall:
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            return StorageCall(session_id=self.session_id, repository=self.repository, operation=name,
                               arguments={key: TypeAdapter(hints[key]).dump_python(value, mode="json")
                                          for key, value in bound.arguments.items() if key != "self"})

        def decode(reply: StorageResult) -> Any:
            raise_domain_failure(reply)
            if reply.error in {"unavailable", "outcome_unknown"}:
                raise PersistenceUnavailableError("Chat storage operation could not be confirmed")
            if reply.error == "conflict":
                raise PersistenceConflictError("Chat storage constraint rejected the operation")
            if reply.error is not None:
                raise ValueError("Chat storage operation was rejected")
            return result_type.validate_json(json.dumps(reply.value), strict=True)

        if inspect.iscoroutinefunction(prototype):
            async def invoke(*args: Any, **kwargs: Any) -> Any:
                call = request(args, kwargs)
                async with self._assets(call):
                    result = decode(await self.transport.invoke_with_host(call, ScopedChatHost(self.host, call)))
                if self._waker is not None and name in {"commit_user_turn_assistant_outcome", "commit_unmanaged_assistant_outcome"}:
                    try:
                        self._waker()
                    except Exception:
                        logger.exception("Assistant-memory outbox wake failed")
                return result
            return invoke
        def invoke(*args: Any, **kwargs: Any) -> Any:
            call = request(args, kwargs)
            return decode(self.transport.invoke_sync_with_host(call, ScopedChatHost(self.host, call)))
        return invoke

    @staticmethod
    @asynccontextmanager
    async def _assets(call: StorageCall):
        values = call.arguments
        guarded = (
            call.operation == "append_message" and values.get("attachment_payloads") is not None
            or call.operation in {"create_user_turn", "create_user_turn_once"} and has_managed_asset_payloads(values.get("attachment_payloads"))
            or call.operation in {"commit_user_turn_assistant_outcome", "commit_unmanaged_assistant_outcome"}
            and has_explicit_asset_payload_map(values.get("attachment_payloads_by_message_id"))
        )
        if guarded:
            async with chat_asset_mutation():
                yield
        else:
            yield
