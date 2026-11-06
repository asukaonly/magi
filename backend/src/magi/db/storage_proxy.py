"""Adapt a typed domain port to validated storage protocol calls."""

from __future__ import annotations

import inspect
import json
from typing import Any, get_type_hints

from pydantic import TypeAdapter

from magi_plugin_sdk.storage import StorageCall, StorageProvider

from ..core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError


class RepositoryProxy:
    def __init__(self, provider: StorageProvider, session_id: str, repository: str, contract: type) -> None:
        self._provider = provider
        self._session_id = session_id
        self._repository = repository
        self._methods = {
            name: method for cls in reversed(contract.__mro__) for name, method in vars(cls).items()
            if not name.startswith("_") and inspect.isfunction(method)
        }

    def __getattr__(self, name: str) -> Any:
        if name not in self._methods:
            raise AttributeError(name)
        prototype = self._methods[name]
        signature = inspect.signature(prototype)
        hints = get_type_hints(prototype)
        result_type = TypeAdapter(hints["return"])

        async def invoke(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            arguments = {
                key: TypeAdapter(hints[key]).dump_python(value, mode="json")
                for key, value in bound.arguments.items() if key != "self"
            }
            reply = await self._provider.invoke(StorageCall(
                session_id=self._session_id, repository=self._repository,
                operation=name, arguments=arguments,
            ))
            if reply.error in {"unavailable", "outcome_unknown"}:
                raise PersistenceUnavailableError("Storage operation could not be confirmed")
            if reply.error == "conflict":
                raise PersistenceConflictError("Storage constraint rejected the write")
            if reply.error is not None:
                raise ValueError("Storage operation was rejected")
            return result_type.validate_json(json.dumps(reply.value), strict=True)

        return invoke
