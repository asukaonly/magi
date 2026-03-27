"""Process-role contracts for backend startup topology."""

from __future__ import annotations

from enum import Enum
from typing import Mapping

PROCESS_ROLE_ENV_VAR = "MAGI_PROCESS_ROLE"


class ProcessRole(str, Enum):
    """Supported backend process roles."""

    API = "api"
    RUNTIME_WORKER = "runtime_worker"

    @property
    def runs_transport(self) -> bool:
        """Return whether the role should host HTTP/WebSocket transport."""
        return self is ProcessRole.API

    @property
    def runs_runtime(self) -> bool:
        """Return whether the role should host the background runtime graph."""
        return self is ProcessRole.RUNTIME_WORKER


def resolve_process_role(
    value: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    default: ProcessRole = ProcessRole.API,
) -> ProcessRole:
    """Resolve the backend process role from explicit input or environment."""
    source_env = env if env is not None else {}
    candidate = value
    if candidate is None or not str(candidate).strip():
        candidate = source_env.get(PROCESS_ROLE_ENV_VAR)
    if candidate is None or not str(candidate).strip():
        return default

    normalized = str(candidate).strip().lower().replace("-", "_")
    try:
        return ProcessRole(normalized)
    except ValueError as exc:
        supported = ", ".join(role.value for role in ProcessRole)
        raise ValueError(
            f"Unsupported process role '{candidate}'. Supported roles: {supported}"
        ) from exc


__all__ = [
    "PROCESS_ROLE_ENV_VAR",
    "ProcessRole",
    "resolve_process_role",
]
