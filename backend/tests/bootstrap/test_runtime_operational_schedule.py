from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.models import AppConfig
from magi.scheduler.contracts import ScheduledTargetType


def test_scheduled_target_type_includes_runtime_operational_gc() -> None:
    assert ScheduledTargetType.RUNTIME_OPERATIONAL_GC == "runtime_operational_gc"
    assert (
        ScheduledTargetType("runtime_operational_gc") is ScheduledTargetType.RUNTIME_OPERATIONAL_GC
    )


@pytest.mark.asyncio
async def test_runtime_operational_gc_contrib_registers_handler_and_schedule() -> None:
    from magi.bootstrap.maintenance import (
        RuntimeOperationalGCScheduleContrib,
        SCHEDULE_ID_RUNTIME_OPERATIONAL_GC,
        TARGET_KEY_RUNTIME_OPERATIONAL_GC,
    )

    registered_handlers: dict[ScheduledTargetType, Any] = {}
    scheduled_intervals: list[dict[str, Any]] = []

    class FakeScheduler:
        def register_handler(self, target_type: ScheduledTargetType, handler: Any) -> None:
            registered_handlers[target_type] = handler

        async def schedule_interval(self, **kwargs: Any) -> None:
            scheduled_intervals.append(dict(kwargs))

        async def unschedule(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("register_schedules should not unschedule when enabled")

    config = AppConfig()
    config.agent.maintenance.interval_seconds = 123.0
    contrib = RuntimeOperationalGCScheduleContrib(
        unified_memory=MagicMock(),
        get_config_func=lambda: config,
    )

    await contrib.register_schedules(FakeScheduler())  # type: ignore[arg-type]

    assert ScheduledTargetType.RUNTIME_OPERATIONAL_GC in registered_handlers
    assert scheduled_intervals == [
        {
            "schedule_id": SCHEDULE_ID_RUNTIME_OPERATIONAL_GC,
            "target_type": ScheduledTargetType.RUNTIME_OPERATIONAL_GC,
            "target_key": TARGET_KEY_RUNTIME_OPERATIONAL_GC,
            "seconds": 123.0,
            "target_payload": {},
        }
    ]


@pytest.mark.asyncio
async def test_runtime_operational_gc_handler_runs_all_runtime_cleanup() -> None:
    from magi.bootstrap.maintenance import RuntimeOperationalGCScheduleContrib

    config = AppConfig()
    config.lifecycle.chat_assets.delete_on_session_delete = True
    config.lifecycle.chat_assets.delete_on_clear_memory = False
    config.lifecycle.chat_assets.orphan_grace_hours = 7
    unified_memory = MagicMock()
    unified_memory.cleanup_runtime_data = AsyncMock(return_value={"expired_sessions": 2})

    runtime_gc = MagicMock()
    runtime_gc.run = AsyncMock(return_value={"llm_usage_raw_deleted": 3})
    chat_asset_gc = MagicMock()
    chat_asset_gc.sweep_orphan_session_assets.return_value = {"chat_asset_orphan_files_deleted": 4}

    with (
        patch(
            "magi.bootstrap.maintenance.RuntimeOperationalGC",
            return_value=runtime_gc,
        ) as runtime_gc_cls,
        patch("magi.bootstrap.maintenance.ChatAssetGC", return_value=chat_asset_gc),
        patch(
            "magi.bootstrap.maintenance.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func, **kwargs: func(**kwargs)),
        ),
    ):
        contrib = RuntimeOperationalGCScheduleContrib(
            unified_memory=unified_memory,
            get_config_func=lambda: config,
            runtime_paths_provider=lambda: SimpleNamespace(runtime_dir="/tmp/runtime"),
        )
        result = await contrib.handle(MagicMock())

    assert result.success is True
    assert result.message == "runtime_operational_gc_ok"
    assert result.stats == {
        "expired_sessions": 2,
        "llm_usage_raw_deleted": 3,
        "chat_asset_orphan_files_deleted": 4,
    }
    unified_memory.cleanup_runtime_data.assert_awaited_once()
    runtime_gc.run.assert_awaited_once()
    runtime_gc_cls.assert_called_once()
    chat_asset_gc.sweep_orphan_session_assets.assert_called_once_with(orphan_grace_hours=7)


@pytest.mark.asyncio
async def test_runtime_operational_gc_skips_orphan_assets_when_disabled() -> None:
    from magi.bootstrap.maintenance import RuntimeOperationalGCScheduleContrib

    config = AppConfig()
    config.lifecycle.chat_assets.delete_on_session_delete = False
    config.lifecycle.chat_assets.delete_on_clear_memory = True
    unified_memory = MagicMock()
    unified_memory.cleanup_runtime_data = AsyncMock(return_value={})
    runtime_gc = MagicMock()
    runtime_gc.run = AsyncMock(return_value={})
    chat_asset_gc = MagicMock()

    with (
        patch(
            "magi.bootstrap.maintenance.RuntimeOperationalGC",
            return_value=runtime_gc,
        ),
        patch("magi.bootstrap.maintenance.ChatAssetGC", return_value=chat_asset_gc),
    ):
        contrib = RuntimeOperationalGCScheduleContrib(
            unified_memory=unified_memory,
            get_config_func=lambda: config,
            runtime_paths_provider=lambda: SimpleNamespace(runtime_dir="/tmp/runtime"),
        )
        result = await contrib.handle(MagicMock())

    assert result.success is True
    chat_asset_gc.sweep_orphan_session_assets.assert_not_called()
