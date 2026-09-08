"""Process-owned identity for restricted memory restore workers."""

from __future__ import annotations

import os
import uuid

_restore_operation_id: str | None = None


def consume_restore_operation() -> str | None:
    """Consume the supervisor binding before any plugin code can run."""
    global _restore_operation_id
    value = os.environ.pop("MAGI_MEMORY_RESTORE_OPERATION_ID", None)
    if value is not None:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise RuntimeError("Restore worker identity is invalid")
    _restore_operation_id = value
    return value


def owns_restore_operation(operation_id: str) -> bool:
    """Only the supervisor-selected operation can cross the private IPC route."""
    return _restore_operation_id == operation_id


def is_restore_worker() -> bool:
    """Return whether normal post-start work is held by restore ownership."""
    return _restore_operation_id is not None
