"""Tests for background-task bootstrap wiring (Phase 4c)."""

from __future__ import annotations

from pathlib import Path

from magi.agent.background import BackgroundTaskRetentionScheduleContrib, BackgroundTaskStore
from magi.bootstrap.background_tasks import build_background_task_wiring
from magi.control.session_store import ControlSessionStore


# ----------------------------------------------------------------------
# build_background_task_wiring
# ----------------------------------------------------------------------


def test_build_background_task_wiring_composes_components(tmp_path: Path) -> None:
    wiring = build_background_task_wiring(
        store_db_path=str(tmp_path / "bg.db"),
        llm_adapter=None,
        llm_pool=None,
        skill_runner=None,
        runtime_trace_store=None,
        chat_task_budget_store=None,
        run_plan_store=ControlSessionStore(),
        max_concurrent=3,
    )
    assert isinstance(wiring.store, BackgroundTaskStore)
    assert wiring.store.db_path == str(tmp_path / "bg.db")
    assert wiring.manager is not None
    assert wiring.launch_service is not None
    assert isinstance(wiring.retention_schedule, BackgroundTaskRetentionScheduleContrib)
