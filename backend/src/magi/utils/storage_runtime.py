"""Verify optional storage clients without contacting external servers."""
from __future__ import annotations

import importlib.util
from collections.abc import Iterable


def installed_storage_backends() -> tuple[str, ...]:
    """Describe the build interpreter so the frozen worker must match it."""
    backends = []
    mysql = [importlib.util.find_spec(name) is not None for name in ("asyncmy", "pymysql")]
    if any(mysql):
        if not all(mysql):
            raise RuntimeError("MySQL packaging requires the complete storage-mysql extra")
        backends.append("mysql")
    if importlib.util.find_spec("chromadb") is not None:
        backends.append("chroma")
    return tuple(backends)


def validate_storage_runtime(backends: Iterable[str]) -> None:
    """Exercise driver and component resolution; never read runtime credentials."""
    for backend in backends:
        if backend == "mysql":
            from packaging.version import Version
            import sqlalchemy
            from sqlalchemy import create_engine
            from sqlalchemy.ext.asyncio import create_async_engine

            if Version(sqlalchemy.__version__) < Version("2.0.55"):
                raise RuntimeError("MySQL storage requires SQLAlchemy 2.0.55 or newer")
            # Engine construction resolves the dynamic dialect and imports DBAPI.
            sync = create_engine("mysql+pymysql://localhost/packaging_check")
            asynchronous = create_async_engine("mysql+asyncmy://localhost/packaging_check")
            sync.dispose()
            asynchronous.sync_engine.dispose()
        elif backend == "chroma":
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
