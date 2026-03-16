from __future__ import annotations

import pytest

from magi.scheduler.runtime import get_scheduler_service, set_scheduler_runtime


def test_scheduler_runtime_tracks_service_without_bootstrap() -> None:
    service = object()

    set_scheduler_runtime(service)

    assert get_scheduler_service() is service

    set_scheduler_runtime(None)


def test_scheduler_runtime_clears_service() -> None:
    set_scheduler_runtime(object())

    set_scheduler_runtime(None)

    assert get_scheduler_service() is None


def test_scheduler_runtime_does_not_expose_refresh_shim() -> None:
    import magi.scheduler.runtime as runtime_module

    with pytest.raises(AttributeError):
        getattr(runtime_module, "request_scheduler_refresh")
