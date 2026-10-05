from __future__ import annotations

import json

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.corrections.models import CorrectionTargetKind
from magi.memory.l2.corrections.revert_blocks import (
    LINEAGE_COLLISION_REVERT_BLOCK,
    block_colliding_correction_lineages,
)


async def _insert_correction(
    db,
    *,
    correction_id: str,
    target_id: str,
    replacement_target_id: str,
    created_at: float,
    slot_key: str = "shared-slot",
    replacement_slot_key: str | None = None,
) -> None:
    before_json = json.dumps(
        {"slot_key": slot_key, "scope_json": "{}"},
        separators=(",", ":"),
    )
    replacement_json = json.dumps(
        {
            "slot_key": replacement_slot_key or slot_key,
            "scope_json": "{}",
        },
        separators=(",", ":"),
    )
    await db.execute(
        """
        INSERT INTO memory_corrections(
            correction_id, request_id, actor_id, target_kind, target_id,
            slot_key, claim_fingerprint, correction_kind, before_json,
            replacement_json, replacement_target_id, state, created_at,
            transition_applied_at
        ) VALUES (?, ?, 'user:self', 'assertion', ?, ?, ?,
                  'record_error', ?, ?, ?, 'active', ?, ?)
        """,
        (
            correction_id,
            f"request-{correction_id}",
            target_id,
            slot_key,
            f"claim-{correction_id}",
            before_json,
            replacement_json,
            replacement_target_id,
            created_at,
            created_at,
        ),
    )


@pytest.mark.asyncio
async def test_runtime_revert_blocker_rejects_a_forked_lineage(
    l2_store_with_schema,
) -> None:
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await _insert_correction(
            db,
            correction_id="fork-root",
            target_id="assertion-a",
            replacement_target_id="assertion-b",
            created_at=1,
        )
        await _insert_correction(
            db,
            correction_id="fork-left",
            target_id="assertion-b",
            replacement_target_id="assertion-c",
            created_at=2,
        )
        await _insert_correction(
            db,
            correction_id="fork-right",
            target_id="assertion-b",
            replacement_target_id="assertion-d",
            created_at=3,
        )

        blocked = await block_colliding_correction_lineages(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            slot_keys={"shared-slot"},
            block_reason=LINEAGE_COLLISION_REVERT_BLOCK,
            created_at=4,
        )
        await db.commit()

    assert blocked == {"fork-root", "fork-left", "fork-right"}

    from magi.memory.l2.corrections.service import MemoryCorrectionConflictError

    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        async with db.execute(
            "SELECT correction_id, block_reason, created_at FROM memory_correction_revert_blocks ORDER BY correction_id"
        ) as cursor:
            rows = [tuple(row) for row in await cursor.fetchall()]
    assert rows == [
        (correction_id, "lineage_collision", 4)
        for correction_id in ["fork-left", "fork-right", "fork-root"]
    ]
    for correction_id in ["fork-left", "fork-right", "fork-root"]:
        with pytest.raises(MemoryCorrectionConflictError) as failure:
            await l2_store_with_schema.revert_assertion_correction(
                correction_id=correction_id,
                request_id=f"revert:{correction_id}",
                actor_id="user:self",
            )
        assert failure.value.code == "correction_lineage_revert_blocked"
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        async with db.execute(
            "SELECT correction_id, state FROM memory_corrections ORDER BY correction_id"
        ) as cursor:
            assert [tuple(row) for row in await cursor.fetchall()] == [
                (correction_id, "active")
                for correction_id in ["fork-left", "fork-right", "fork-root"]
            ]


@pytest.mark.asyncio
async def test_runtime_revert_blocker_keeps_one_linear_lineage(
    l2_store_with_schema,
) -> None:
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await _insert_correction(
            db,
            correction_id="chain-first",
            target_id="assertion-a",
            replacement_target_id="assertion-b",
            created_at=1,
        )
        await _insert_correction(
            db,
            correction_id="chain-second",
            target_id="assertion-b",
            replacement_target_id="assertion-c",
            created_at=2,
        )

        blocked = await block_colliding_correction_lineages(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            slot_keys={"shared-slot"},
            block_reason=LINEAGE_COLLISION_REVERT_BLOCK,
            created_at=3,
        )
        await db.commit()

    assert blocked == set()


@pytest.mark.asyncio
async def test_runtime_revert_blocker_uses_shared_replacement_slot(
    l2_store_with_schema,
) -> None:
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await _insert_correction(
            db,
            correction_id="replacement-left",
            target_id="assertion-a",
            replacement_target_id="assertion-shared",
            created_at=1,
            slot_key="before-left",
            replacement_slot_key="shared-output",
        )
        await _insert_correction(
            db,
            correction_id="replacement-right",
            target_id="assertion-b",
            replacement_target_id="assertion-shared",
            created_at=2,
            slot_key="before-right",
            replacement_slot_key="shared-output",
        )

        blocked = await block_colliding_correction_lineages(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            slot_keys={"shared-output"},
            block_reason=LINEAGE_COLLISION_REVERT_BLOCK,
            created_at=3,
        )
        await db.commit()

    assert blocked == {"replacement-left", "replacement-right"}

    from magi.memory.l2.corrections.service import MemoryCorrectionConflictError

    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        async with db.execute(
            "SELECT correction_id, block_reason, created_at FROM memory_correction_revert_blocks ORDER BY correction_id"
        ) as cursor:
            rows = [tuple(row) for row in await cursor.fetchall()]
    assert rows == [
        (correction_id, "lineage_collision", 3)
        for correction_id in ["replacement-left", "replacement-right"]
    ]
    for correction_id in ["replacement-left", "replacement-right"]:
        with pytest.raises(MemoryCorrectionConflictError) as failure:
            await l2_store_with_schema.revert_assertion_correction(
                correction_id=correction_id,
                request_id=f"revert:{correction_id}",
                actor_id="user:self",
            )
        assert failure.value.code == "correction_lineage_revert_blocked"
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        async with db.execute(
            "SELECT correction_id, state FROM memory_corrections ORDER BY correction_id"
        ) as cursor:
            assert [tuple(row) for row in await cursor.fetchall()] == [
                (correction_id, "active")
                for correction_id in ["replacement-left", "replacement-right"]
            ]
