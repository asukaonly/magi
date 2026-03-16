"""API-facing message bus binding access."""

from __future__ import annotations

from ...core.runtime_bindings import require_message_bus

__all__ = ["require_message_bus"]
