"""Phase G+1 Task 11 — NotificationRelay deprecation guards.

Verifies the legacy polling relay is marked deprecated and is no longer
re-exported from the ``magi.channels`` package surface.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_notification_relay_init_emits_deprecation_warning() -> None:
    """Constructing NotificationRelay must surface a DeprecationWarning."""
    from magi.channels.notification_relay import NotificationRelay
    from magi.channels.registry import ChannelRegistry
    from magi.channels.session_mapper import ChannelSessionMapper

    registry = ChannelRegistry()
    mapper = MagicMock(spec=ChannelSessionMapper)
    trace_store = MagicMock()

    with pytest.warns(DeprecationWarning, match="deprecated"):
        NotificationRelay(
            registry=registry,
            session_mapper=mapper,
            trace_store=trace_store,
        )


def test_notification_relay_not_exported_from_package() -> None:
    """`from magi.channels import NotificationRelay` must fail."""
    with pytest.raises(ImportError):
        from magi.channels import NotificationRelay  # noqa: F401
