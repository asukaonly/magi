"""Tests for L3 digest schedule handler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.memory.l3.digest_schedule import (
    SCHEDULE_ID_L3_DIGEST,
    TARGET_KEY_L3_DIGEST,
    L3DigestScheduleContrib,
    _build_persona_context,
    handle_l3_digest,
)
from magi.scheduler.contracts import (
    ScheduleDefinition,
    ScheduledExecutionContext,
    ScheduledTargetState,
    ScheduledTargetType,
    TriggerDefinition,
    TriggerType,
)


def _make_context() -> ScheduledExecutionContext:
    return ScheduledExecutionContext(
        schedule=ScheduleDefinition(
            schedule_id=SCHEDULE_ID_L3_DIGEST,
            target_type=ScheduledTargetType.MEMORY_L3_DIGEST,
            target_key=TARGET_KEY_L3_DIGEST,
            trigger=TriggerDefinition(trigger_type=TriggerType.INTERVAL),
        ),
        target_state=ScheduledTargetState(
            target_type=ScheduledTargetType.MEMORY_L3_DIGEST,
            target_key=TARGET_KEY_L3_DIGEST,
        ),
        runtime_dir=Path("/tmp"),
        triggered_at=1000.0,
    )


@pytest.mark.asyncio
async def test_handle_l3_digest_skips_when_disabled() -> None:
    l3_settings = SimpleNamespace(enabled=True, digest_enabled=False)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    with patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg):
        result = await handle_l3_digest(_make_context())

    assert result.success is True
    assert "disabled" in result.message


@pytest.mark.asyncio
async def test_handle_l3_digest_skips_when_l3_disabled() -> None:
    l3_settings = SimpleNamespace(enabled=False, digest_enabled=True)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    with patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg):
        result = await handle_l3_digest(_make_context())

    assert result.success is True
    assert "disabled" in result.message


@pytest.mark.asyncio
async def test_handle_l3_digest_generates_summary() -> None:
    l3_settings = SimpleNamespace(enabled=True, digest_enabled=True)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    mock_l1 = MagicMock()
    mock_l3 = MagicMock()
    mock_l3.generate_temporal_summary = AsyncMock(
        return_value={"summary_id": "sum-1", "content": "A productive day."}
    )
    mock_unified = MagicMock(l1=mock_l1, l3=mock_l3)

    with (
        patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg),
        patch("magi.memory.l3.digest_schedule.require_unified_memory", return_value=mock_unified),
        patch("magi.memory.l3.digest_schedule._build_persona_context", return_value=None),
    ):
        result = await handle_l3_digest(_make_context())

    assert result.success is True
    assert result.stats["generated"] == 1
    assert result.stats["errors"] == 0
    mock_l3.generate_temporal_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_l3_digest_handles_generation_error() -> None:
    l3_settings = SimpleNamespace(enabled=True, digest_enabled=True)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    mock_l1 = MagicMock()
    mock_l3 = MagicMock()
    mock_l3.generate_temporal_summary = AsyncMock(side_effect=RuntimeError("LLM down"))
    mock_unified = MagicMock(l1=mock_l1, l3=mock_l3)

    with (
        patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg),
        patch("magi.memory.l3.digest_schedule.require_unified_memory", return_value=mock_unified),
        patch("magi.memory.l3.digest_schedule._build_persona_context", return_value=None),
    ):
        result = await handle_l3_digest(_make_context())

    assert result.success is False
    assert result.stats["errors"] == 1


@pytest.mark.asyncio
async def test_handle_l3_digest_skips_when_unified_memory_unavailable() -> None:
    l3_settings = SimpleNamespace(enabled=True, digest_enabled=True)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    with (
        patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg),
        patch(
            "magi.memory.l3.digest_schedule.require_unified_memory",
            side_effect=RuntimeError("not bound"),
        ),
    ):
        result = await handle_l3_digest(_make_context())

    assert result.success is True
    assert "unavailable" in result.message


def test_build_persona_context_returns_none_for_default() -> None:
    with patch("magi.memory.l3.digest_schedule.get_current_personality", return_value="default"):
        result = _build_persona_context()
    assert result is None


def test_build_persona_context_returns_dict_for_valid_personality() -> None:
    fake_persona = SimpleNamespace(
        basic_profile=SimpleNamespace(name="Melchior"),
        core_identity=SimpleNamespace(
            inner_narrative="A wise scholar",
            language_fingerprint="warm and reflective",
            attention_bias="insight, growth",
        ),
    )
    fake_config = SimpleNamespace(persona_entity=fake_persona)

    with (
        patch("magi.memory.l3.digest_schedule.get_current_personality", return_value="melchior"),
        patch("magi.memory.l3.digest_schedule.get_current_personality_config", return_value=fake_config),
    ):
        result = _build_persona_context()

    assert result is not None
    assert result["name"] == "Melchior"
    assert result["tone"] == "warm and reflective"
    assert "insight" in result["keywords"]


@pytest.mark.asyncio
async def test_contrib_registers_handler_and_schedule() -> None:
    l3_settings = SimpleNamespace(digest_enabled=True, digest_interval_hours=12)
    mem_settings = SimpleNamespace(l3=l3_settings)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=mem_settings))

    mock_scheduler = MagicMock()
    mock_scheduler.schedule_interval = AsyncMock()
    mock_scheduler.unschedule = AsyncMock()

    contrib = L3DigestScheduleContrib()
    with patch("magi.memory.l3.digest_schedule.get_config", return_value=cfg):
        await contrib.register_schedules(mock_scheduler)

    mock_scheduler.register_handler.assert_called_once_with(
        ScheduledTargetType.MEMORY_L3_DIGEST, handle_l3_digest
    )
    mock_scheduler.schedule_interval.assert_awaited_once()
    call_kwargs = mock_scheduler.schedule_interval.call_args
    assert call_kwargs.kwargs["seconds"] == 12 * 3600


@pytest.mark.asyncio
async def test_contrib_unregisters_schedule() -> None:
    mock_scheduler = MagicMock()
    mock_scheduler.unschedule = AsyncMock()

    contrib = L3DigestScheduleContrib()
    await contrib.unregister_schedules(mock_scheduler)

    mock_scheduler.unschedule.assert_awaited_once()
