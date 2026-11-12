"""Validated dispatch for explicit repository method tables."""

from __future__ import annotations

import inspect
import json
import asyncio
from collections.abc import Callable, Mapping
from typing import Any, get_type_hints

from pydantic import ConfigDict, TypeAdapter, ValidationError, create_model

from .storage import StorageCall, StorageResult
from .async_cleanup import finish_cleanup
from .storage_ports.channels import ChannelSessionRepository, ChannelBindingSettingsRepository, DeliveryReceiptsRepository
from .storage_ports.outreach import OutreachOutboxRepository, OutreachDeliveryLogRepository
from .storage_ports.events import EventStorageOperations
from .storage_ports.chat import ChatRepository
from .storage_ports.chat_reads import ChatStorageReads
from .storage_errors import DOMAIN_ERRORS, domain_failure

CHANNEL_REPOSITORY_CONTRACTS = {
    "sessions": ChannelSessionRepository, "receipts": DeliveryReceiptsRepository,
    "binding_settings": ChannelBindingSettingsRepository, "outbox": OutreachOutboxRepository,
    "delivery_log": OutreachDeliveryLogRepository,
}
EVENT_REPOSITORY_CONTRACTS = {"events": EventStorageOperations}
CHAT_REPOSITORY_CONTRACTS = {"chat": ChatRepository, "reads": ChatStorageReads}
CHAT_REPOSITORY_METHODS = {
    repository: tuple(dict.fromkeys(
        name for base in reversed(contract.__mro__) for name, method in vars(base).items()
        if not name.startswith("_") and inspect.isfunction(method)
        and name != "set_assistant_memory_outbox_waker"
    ))
    for repository, contract in CHAT_REPOSITORY_CONTRACTS.items()
}


CHANNEL_REPOSITORY_METHODS = {
    "sessions": (
        "initialize", "lookup", "list_all", "lookup_by_session", "delete_mapping",
        "clear_conversation_state", "get_notification_cursor", "update_notification_cursor",
        "get_relay_cursor", "update_relay_cursor", "insert", "touch",
    ),
    "receipts": ("initialize", "save_receipts", "list_receipts", "clear_receipts"),
    "binding_settings": ("initialize", "get", "set_auto_approve", "list_all"),
    "outbox": (
        "enqueue", "list_due", "mark_status", "begin_delivery_attempt",
        "restore_pending_after_unattempted_delivery", "reschedule",
    ),
    "delivery_log": ("record", "was_delivered", "count_for_user_since"),
}


class RepositoryDispatcher:
    """Resolve names only from the host's public operation table."""

    def __init__(
        self, repositories: Mapping[str, object], methods: Mapping[str, tuple[str, ...]],
        contracts: Mapping[str, type],
    ) -> None:
        self._methods: dict[tuple[str, str], tuple[Callable[..., Any], Any, Any]] = {}
        if set(repositories) != set(methods):
            raise ValueError("Storage repository set does not match its contract")
        for repository, names in methods.items():
            for name in names:
                function = getattr(repositories[repository], name)
                prototype = getattr(contracts[repository], name)
                signature = inspect.signature(prototype)
                hints = get_type_hints(prototype)
                parameters = {}
                for key, parameter in signature.parameters.items():
                    if key == "self":
                        continue
                    if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
                        raise TypeError("Storage methods require explicit parameters")
                    if key not in hints:
                        raise TypeError("Storage parameters require public type annotations")
                    parameters[key] = (
                        hints[key], ... if parameter.default is parameter.empty else parameter.default,
                    )
                arguments = create_model(
                    f"{repository}_{name}", __config__=ConfigDict(extra="forbid"), **parameters,
                )
                if "return" not in hints:
                    raise TypeError("Storage results require public type annotations")
                self._methods[repository, name] = (function, arguments, TypeAdapter(hints["return"]))

    async def invoke(self, request: StorageCall) -> StorageResult:
        entry = self._methods.get((request.repository, request.operation))
        if entry is None:
            return StorageResult(error="invalid")
        function, arguments, result_type = entry
        try:
            values = arguments.model_validate_json(json.dumps(request.arguments), strict=True)
        except ValidationError:
            return StorageResult(error="invalid")
        keywords = {key: getattr(values, key) for key in type(values).model_fields}
        try:
            if inspect.iscoroutinefunction(function):
                result = await function(**keywords)
            else:
                result = await finish_cleanup(asyncio.to_thread(function, **keywords))
                if inspect.isawaitable(result):
                    result = await result
        except tuple(DOMAIN_ERRORS.values()) as exc:
            return domain_failure(exc)
        result = result_type.validate_python(result)
        return StorageResult(value=result_type.dump_python(result, mode="json"))


EVENT_REPOSITORY_METHODS = {
    "events": (
        'append',
        'find_by_idempotency',
        'get',
        'query_events',
        'read_event_overview',
        'get_event_timestamps',
        'get_evidence_records',
        'get_raw_event_turn_ids',
        'get_raw_event_source_identities',
        'fetch_events',
        'query_session_event_window',
        'summarize_event_sources',
        'count_events',
        'list_compressible_event_page',
        'list_source_facets',
        'count_source_facets',
        'find_events_by_source_facets',
        'rebuild_source_facets',
        'prepare_event_deletion',
        'soft_delete_events',
        'purge_deleted_events',
        'list_active_event_ids_by_entity',
        'list_raw_event_ids_by_entity',
        'list_active_event_ids_by_time_range',
        'list_raw_event_ids_by_time_range',
        'list_active_event_ids_by_chat_sources',
        'list_raw_event_ids_by_chat_sources',
        'list_active_event_ids_by_chat_message',
        'list_raw_event_ids_by_chat_message',
        'get_pinned_payloads',
        'prune_pinned_payloads',
        'list_ready_cognition_handoffs',
        'complete_cognition_handoff',
        'retry_cognition_handoff',
        'write_event_entities',
        'replace_projected_event_entities_batch',
        'align_entity_link_projection_clear_generation',
        'get_entity_event_ids',
        'get_event_entity_ids',
        'expand_by_entities',
        'resolve_event_entities',
        'find_events_by_entities',
        'filter_ids_by_user',
        'bm25_search',
        'backfill_fts',
        'count_pending_embeddings',
        'event_scan_high_water',
        'embedding_rebuild_page',
        'get_embedding_sources',
        'publish_event_embeddings',
        'remove_event_embedding_chunks',
        'fetch_embedding_chunks',
        'visible_embedding_chunk_ids',
        'initialize',
        'rebuild_chat_session_projection',
        'retire_chat_session_projection',
        'count_evidence_backfill',
        'scan_evidence_backfill',
        'apply_evidence_annotations',
        'get_clear_state',
        'clear_events',
    ),
}
