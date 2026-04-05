"""Process-role contracts for backend startup topology.

In the current architecture only IPC_WORKER is used: the Rust gateway
owns HTTP/WebSocket transport and the Python sidecar runs agent runtime
with an IPC server.
"""

from __future__ import annotations

PROCESS_ROLE_ENV_VAR = "MAGI_PROCESS_ROLE"
PROCESS_ROLE_VALUE = "ipc_worker"


__all__ = [
    "PROCESS_ROLE_ENV_VAR",
    "PROCESS_ROLE_VALUE",
]
