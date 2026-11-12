"""Invocation-scoped chat host queries over the supervised worker channel."""

from __future__ import annotations

import inspect
import json
from typing import Any, get_type_hints
from pydantic import TypeAdapter

from .host import ChatStorageHost
from ..storage import StorageResult
from ..storage_errors import raise_domain_failure

HOST_METHODS = (
    "prepare_assets", "claim_workspace_identity", "list_snapshot_asset_references",
    "get_read_revision", "get_trace_summary", "get_turn_activity_map",
)


class RemoteChatStorageHost:
    def __getattr__(self, name: str) -> Any:
        if name not in HOST_METHODS:
            raise AttributeError(name)
        prototype = getattr(ChatStorageHost, name)
        signature = inspect.signature(prototype)
        hints = get_type_hints(prototype)

        def call(*args: Any, **kwargs: Any) -> Any:
            from ..worker import get_host
            bound = signature.bind(self, *args, **kwargs)
            values = {key: TypeAdapter(hints[key]).dump_python(value, mode="json")
                      for key, value in bound.arguments.items() if key != "self"}
            server = get_host().server
            future = server.callback("storage", {"method": name, "arguments": values})
            reply = StorageResult.model_validate(future.result(timeout=server.callback_timeout))
            raise_domain_failure(reply)
            if reply.error is not None:
                raise ValueError("Host storage context was rejected")
            return TypeAdapter(hints["return"]).validate_json(json.dumps(reply.value), strict=True)

        return call
