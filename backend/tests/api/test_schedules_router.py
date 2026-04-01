"""Tests for the scheduler REST API router."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.api.routers.schedules import (
    _resolve_target_type,
    _resolve_trigger_type,
    _serialize_schedule,
)
from magi.scheduler.contracts import (
    ScheduleDefinition,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


class TestSerializeSchedule:
    def test_basic(self):
        sched = ScheduleDefinition(
            schedule_id="s1",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="plugin:src",
            trigger=TriggerDefinition(TriggerType.INTERVAL, {"seconds": 60}),
            target_payload={"plugin_id": "cal"},
            metadata={"note": "test"},
            job_id="j1",
        )
        result = _serialize_schedule(sched)
        assert result["schedule_id"] == "s1"
        assert result["target_type"] == "sensor_sync"
        assert result["trigger"]["trigger_type"] == "interval"
        assert result["trigger"]["config"] == {"seconds": 60}
        assert result["target_payload"]["plugin_id"] == "cal"
        assert result["enabled"] is True
        assert result["job_id"] == "j1"

    def test_disabled_schedule(self):
        sched = ScheduleDefinition(
            schedule_id="s2",
            target_type=ScheduledTargetType.MEMORY_L2_MAINTENANCE,
            target_key="l2",
            trigger=TriggerDefinition(TriggerType.CRON, {"hour": "3"}),
            enabled=False,
        )
        result = _serialize_schedule(sched)
        assert result["enabled"] is False
        assert result["job_id"] is None


class TestResolveTargetType:
    def test_valid(self):
        assert _resolve_target_type("sensor_sync") is ScheduledTargetType.SENSOR_SYNC

    def test_invalid(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _resolve_target_type("unknown_type")
        assert exc_info.value.status_code == 400


class TestResolveTriggerType:
    def test_valid(self):
        assert _resolve_trigger_type("cron") is TriggerType.CRON

    def test_invalid(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _resolve_trigger_type("bad")
        assert exc_info.value.status_code == 400


class TestListExecutions:
    """Test list_executions repository method."""

    @pytest.mark.asyncio
    async def test_list_returns_records(self, tmp_path):
        from magi.scheduler.repository import ScheduleRepository

        repo = ScheduleRepository(tmp_path / "sched.db")
        await repo.initialize()
        # Create a schedule and execution record.
        sched = ScheduleDefinition(
            schedule_id="s1",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="p:s",
            trigger=TriggerDefinition(TriggerType.ONCE, {"run_at": 1000}),
        )
        await repo.upsert_schedule(sched)
        exec_id = await repo.create_execution_record(
            schedule_id="s1",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="p:s",
            manual=False,
            started_at=1000.0,
        )
        results = await repo.list_executions(schedule_id="s1", limit=10)
        assert len(results) == 1
        assert results[0]["execution_id"] == exec_id
        assert results[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_all_executions(self, tmp_path):
        from magi.scheduler.repository import ScheduleRepository

        repo = ScheduleRepository(tmp_path / "sched.db")
        await repo.initialize()
        sched = ScheduleDefinition(
            schedule_id="s1",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="p:s",
            trigger=TriggerDefinition(TriggerType.ONCE, {"run_at": 1000}),
        )
        await repo.upsert_schedule(sched)
        await repo.create_execution_record(
            schedule_id="s1",
            target_type=ScheduledTargetType.SENSOR_SYNC,
            target_key="p:s",
            manual=True,
            started_at=2000.0,
        )
        # No schedule_id filter → returns all.
        results = await repo.list_executions(limit=5)
        assert len(results) == 1
        assert results[0]["manual"] is True

    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_path):
        from magi.scheduler.repository import ScheduleRepository

        repo = ScheduleRepository(tmp_path / "sched.db")
        await repo.initialize()
        results = await repo.list_executions(limit=10)
        assert results == []
