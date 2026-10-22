"""MySQL connection and transaction infrastructure for repository adapters."""

from __future__ import annotations

import os
import ssl
from contextlib import asynccontextmanager
from typing import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import URL
from sqlalchemy.exc import DBAPIError, IntegrityError, TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from ..core.async_cleanup import finish_cleanup
from ..core.persistence_errors import PersistenceConflictError, PersistenceUnavailableError


class MysqlSettings(BaseModel):
    """Server-owned connection settings; credentials stay in the environment."""

    model_config = ConfigDict(extra="forbid")
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    user: str = Field(min_length=1, max_length=128)
    password_env: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    tls: bool = True
    ca_file: str | None = None
    connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    read_timeout_seconds: int = Field(default=30, ge=1, le=300)
    pool_size: int = Field(default=5, ge=1, le=32)


class MysqlDatabase:
    """Own a bounded pool; never replay writes after an ambiguous connection loss."""

    def __init__(self, settings: MysqlSettings) -> None:
        password = os.environ.get(settings.password_env)
        if password is None:
            raise ValueError("MySQL password environment variable is not configured")
        if not settings.tls and settings.host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote MySQL connections require TLS")
        if settings.ca_file and not settings.tls:
            raise ValueError("MySQL CA file requires TLS")
        tls_context = ssl.create_default_context(cafile=settings.ca_file) if settings.tls else None
        self._engine = create_async_engine(
            URL.create(
                "mysql+asyncmy", username=settings.user, password=password,
                host=settings.host, port=settings.port, database=settings.database,
                query={"charset": "utf8mb4"},
            ),
            pool_size=settings.pool_size, max_overflow=0, pool_timeout=5,
            pool_pre_ping=True, pool_recycle=300,
            isolation_level="READ COMMITTED", hide_parameters=True,
            connect_args={
                "connect_timeout": settings.connect_timeout_seconds,
                "read_timeout": settings.read_timeout_seconds,
                "ssl": tls_context, "local_infile": False,
                "init_command": "SET SESSION sql_mode='STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'",
            },
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Commit exactly once, roll back failures, and drain cleanup on cancellation."""
        connection: AsyncConnection | None = None
        try:
            connection = await self._engine.connect()
            await connection.begin()
            yield connection
            await connection.commit()
        except IntegrityError as exc:
            raise PersistenceConflictError("Storage constraint rejected the write") from exc
        except (DBAPIError, PoolTimeoutError) as exc:
            raise PersistenceUnavailableError("Storage operation could not be confirmed") from exc
        finally:
            if connection is not None:
                await finish_cleanup(connection.close())

    async def close(self) -> None:
        """Release every pooled connection before lifecycle shutdown completes."""
        await finish_cleanup(self._engine.dispose())
