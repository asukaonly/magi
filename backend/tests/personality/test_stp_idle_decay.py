"""Tests for STP idle-round state decay in EmotionalStateEngine."""
from __future__ import annotations

import os
import tempfile

import pytest

from magi.personality.emotional_state import EmotionalStateEngine


@pytest.fixture
async def engine():
    """Create a temporary EmotionalStateEngine for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "emotion.db")
        eng = EmotionalStateEngine(db_path)
        await eng.init()
        yield eng


class TestStpIdleDecay:
    @pytest.mark.asyncio
    async def test_trigger_activates_state(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == "crisis"
        assert state.active_stp_state_name == "Emergency Mode"
        assert state.stp_idle_rounds == 0

    @pytest.mark.asyncio
    async def test_idle_rounds_increment(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        # 3 idle turns — no trigger
        for _ in range(3):
            await engine.update_stp_trigger("", "")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == "crisis"
        assert state.stp_idle_rounds == 3

    @pytest.mark.asyncio
    async def test_idle_reset_after_threshold(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        # 5 idle turns (default threshold)
        for _ in range(5):
            await engine.update_stp_trigger("", "")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == ""
        assert state.active_stp_state_name == ""
        assert state.stp_idle_rounds == 0

    @pytest.mark.asyncio
    async def test_re_trigger_resets_idle_counter(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        # 3 idle turns
        for _ in range(3):
            await engine.update_stp_trigger("", "")
        # Re-trigger
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == "crisis"
        assert state.stp_idle_rounds == 0

    @pytest.mark.asyncio
    async def test_custom_idle_reset_rounds(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode", idle_reset_rounds=2)
        await engine.update_stp_trigger("", "", idle_reset_rounds=2)
        state = await engine.get_current_state()
        assert state.active_stp_trigger == "crisis"  # Not yet cleared (1 idle)
        await engine.update_stp_trigger("", "", idle_reset_rounds=2)
        state = await engine.get_current_state()
        assert state.active_stp_trigger == ""  # Cleared after 2 idle

    @pytest.mark.asyncio
    async def test_no_active_state_idle_is_noop(self, engine):
        # No active trigger — idle should not accumulate
        await engine.update_stp_trigger("", "")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == ""
        assert state.stp_idle_rounds == 0

    @pytest.mark.asyncio
    async def test_different_trigger_replaces_state(self, engine):
        await engine.update_stp_trigger("crisis", "Emergency Mode")
        await engine.update_stp_trigger("intimacy", "Inner Circle")
        state = await engine.get_current_state()
        assert state.active_stp_trigger == "intimacy"
        assert state.active_stp_state_name == "Inner Circle"
        assert state.stp_idle_rounds == 0
