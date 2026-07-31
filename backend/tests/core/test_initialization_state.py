from __future__ import annotations

import asyncio
import sqlite3

import pytest

from magi.core.initialization_state import (
    InitializationStateStore,
    InitializationStepBusyError,
)


@pytest.mark.asyncio
async def test_run_step_skips_completed_revision_and_fingerprint(tmp_path) -> None:
    store = InitializationStateStore(tmp_path / "bootstrap_state.db")
    await store.initialize()
    calls: list[str] = []

    async def operation() -> str:
        calls.append("run")
        return "ok"

    first = await store.run_step(
        step_id="builtin_personas:en",
        revision="1",
        fingerprint="content-a",
        operation=operation,
    )
    second = await store.run_step(
        step_id="builtin_personas:en",
        revision="1",
        fingerprint="content-a",
        operation=operation,
    )

    assert first == (True, "ok")
    assert second == (False, None)
    assert calls == ["run"]
    record = await store.get_step("builtin_personas:en")
    assert record is not None
    assert record.status == "completed"
    assert record.completed_revision == "1"
    assert record.completed_fingerprint == "content-a"
    assert record.attempt_count == 1


@pytest.mark.asyncio
async def test_failed_update_preserves_last_success_and_retries(tmp_path) -> None:
    store = InitializationStateStore(tmp_path / "bootstrap_state.db")
    await store.initialize()

    async def initial() -> None:
        return None

    await store.run_step(
        step_id="system_schedules",
        revision="1",
        fingerprint="old",
        operation=initial,
    )

    async def fail() -> None:
        raise RuntimeError("broken update")

    with pytest.raises(RuntimeError, match="broken update"):
        await store.run_step(
            step_id="system_schedules",
            revision="2",
            fingerprint="new",
            operation=fail,
        )

    failed = await store.get_step("system_schedules")
    assert failed is not None
    assert failed.status == "failed"
    assert failed.completed_revision == "1"
    assert failed.completed_fingerprint == "old"
    assert failed.attempt_revision == "2"
    assert failed.last_error == "RuntimeError: broken update"

    ran, _ = await store.run_step(
        step_id="system_schedules",
        revision="2",
        fingerprint="new",
        operation=initial,
    )
    assert ran is True
    completed = await store.get_step("system_schedules")
    assert completed is not None
    assert completed.status == "completed"
    assert completed.completed_revision == "2"
    assert completed.attempt_count == 3


@pytest.mark.asyncio
async def test_live_process_cannot_claim_the_same_step(tmp_path) -> None:
    db_path = tmp_path / "bootstrap_state.db"
    owner = InitializationStateStore(db_path)
    contender = InitializationStateStore(db_path)
    await owner.initialize()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> None:
        started.set()
        await release.wait()

    owner_task = asyncio.create_task(
        owner.run_step(
            step_id="config_layout",
            revision="1",
            fingerprint=None,
            operation=blocked,
        )
    )
    await started.wait()
    try:
        with pytest.raises(InitializationStepBusyError):
            await contender.run_step(
                step_id="config_layout",
                revision="1",
                fingerprint=None,
                operation=lambda: asyncio.sleep(0),
            )
    finally:
        release.set()
        await owner_task


@pytest.mark.asyncio
async def test_interrupted_dead_owner_is_reclaimed(tmp_path) -> None:
    db_path = tmp_path / "bootstrap_state.db"
    store = InitializationStateStore(db_path)
    await store.initialize()
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO initialization_steps (
                step_id, status, attempt_revision, attempt_count, owner_token,
                owner_pid, started_at, updated_at
            ) VALUES ('interrupted', 'running', '1', 1, 'dead', 99999999, 1, 1)
            """
        )

    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1

    ran, _ = await store.run_step(
        step_id="interrupted",
        revision="1",
        fingerprint=None,
        operation=operation,
    )

    assert ran is True
    assert calls == 1
    record = await store.get_step("interrupted")
    assert record is not None
    assert record.status == "completed"
    assert record.attempt_count == 2
