"""Invocation-bound typed host RPC client for external tools."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable

from .capabilities import (
    HOST_METHODS,
    AskUserRequest,
    AskUserResult,
    HostMethod,
    MemorySearchRequest,
    MemorySearchResult,
)

MAX_HOST_SERVICE_BYTES = 128 * 1024
HostCallback = Callable[[str, dict[str, object]], Awaitable[object]]


def validate_host_payload(value: object) -> None:
    """Require bounded plain JSON, rejecting nested SDK objects and non-finite values."""
    count = 0

    def visit(item: object, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > 8 or count > 512:
            raise ValueError("Host service payload structure exceeds its limit")
        if item is None or type(item) in (str, int, float, bool):
            return
        if type(item) is list:
            for child in item:
                visit(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                visit(child, depth + 1)
            return
        raise ValueError("Host service payload must contain only plain JSON values")

    visit(value, 0)
    if (
        len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        > MAX_HOST_SERVICE_BYTES
    ):
        raise ValueError("Host service payload exceeds its byte limit")


@runtime_checkable
class HostServices(Protocol):
    @property
    def permitted_methods(self) -> tuple[HostMethod, ...]: ...

    async def memory_search(
        self, request: MemorySearchRequest
    ) -> MemorySearchResult: ...

    async def ask_user(self, request: AskUserRequest) -> AskUserResult: ...


class RemoteHostServices:
    """Use only methods issued for this tool invocation by the host.

    The method list is a discovery hint. The host independently checks live
    authorization on every call, including calls from a modified worker.
    """

    def __init__(
        self, callback: HostCallback, permitted_methods: Sequence[HostMethod] = ()
    ) -> None:
        if any(method not in HOST_METHODS for method in permitted_methods):
            raise ValueError("Unknown public host method")
        self._callback = callback
        self._permitted_methods = tuple(dict.fromkeys(permitted_methods))

    @property
    def permitted_methods(self) -> tuple[HostMethod, ...]:
        return self._permitted_methods

    async def _call(self, method: HostMethod, request: dict[str, object]) -> object:
        if method not in self._permitted_methods:
            raise PermissionError("Host method was not granted to this invocation")
        validate_host_payload(request)
        response = await self._callback(
            "host_service", {"method": method, "request": request}
        )
        validate_host_payload(response)
        return response

    async def memory_search(self, request: MemorySearchRequest) -> MemorySearchResult:
        request = MemorySearchRequest.model_validate(request.model_dump(mode="json"))
        result = MemorySearchResult.model_validate(
            await self._call("memory.search", request.model_dump(mode="json"))
        )
        if len(result.findings) > request.limit:
            raise ValueError("Host returned more findings than requested")
        return result

    async def ask_user(self, request: AskUserRequest) -> AskUserResult:
        request = AskUserRequest.model_validate(request.model_dump(mode="json"))
        return AskUserResult.model_validate(
            await self._call("interaction.ask", request.model_dump(mode="json"))
        )


__all__ = ["HostServices", "RemoteHostServices"]
