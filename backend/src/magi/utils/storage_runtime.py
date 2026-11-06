"""Verify optional storage clients without contacting external servers."""
from __future__ import annotations

import importlib.util
from collections.abc import Iterable


def installed_storage_backends() -> tuple[str, ...]:
    """Describe the build interpreter so the frozen worker must match it."""
    backends = []
    if importlib.util.find_spec("chromadb") is not None:
        backends.append("chroma")
    return tuple(backends)


def validate_storage_runtime(backends: Iterable[str]) -> None:
    """Exercise driver and component resolution; never read runtime credentials."""
    for backend in backends:
        if backend == "chroma":
            from chromadb.api.async_api import AsyncServerAPI
            from chromadb.config import Settings, System

            system = System(Settings(
                chroma_api_impl="chromadb.api.async_fastapi.AsyncFastAPI",
                chroma_server_host="127.0.0.1", chroma_server_http_port=1,
                anonymized_telemetry=False,
            ))
            # Resolve HTTP and telemetry components without starting a network client.
            system.instance(AsyncServerAPI)
        else:
            raise ValueError("Unknown storage runtime")
