import asyncio
import importlib.util
from pathlib import Path

import aiosqlite
import pytest

# scripts/ is not on the pytest import path, so load the operational report by
# file path instead of depending on packaging side effects.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evidence_stats.py"
_SPEC = importlib.util.spec_from_file_location("evidence_stats", _SCRIPT_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
compute_evidence_stats = _MODULE.compute_evidence_stats


_SCHEMA = """
CREATE TABLE fact_events (
    event_id TEXT PRIMARY KEY,
    evidence_status INTEGER NOT NULL DEFAULT 1,
    evidence_class INTEGER NOT NULL DEFAULT 1,
    l1_retrieval_scope INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT
);
"""


async def _seed(db_path):
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        rows = [
            # evidence_class: 2=user_self_report, 9=user_question, 1=unknown
            # evidence_status: 2=classified, 3=classification_error
            ("e1", 2, 2, 2, '{"_evidence": {"reason_code": "user_default"}}'),
            ("e2", 2, 2, 2, '{"_evidence": {"reason_code": "user_default"}}'),
            ("e3", 2, 9, 3, '{"_evidence": {"reason_code": "user_question_lead_or_mark"}}'),
            ("e4", 3, 1, 1, None),  # classification_error, no reason_code
        ]
        await db.executemany(
            "INSERT INTO fact_events(event_id, evidence_status, evidence_class, "
            "l1_retrieval_scope, metadata_json) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await db.commit()


def test_compute_evidence_stats(tmp_path):
    db_path = str(tmp_path / "l1.db")
    asyncio.run(_seed(db_path))
    stats = asyncio.run(compute_evidence_stats(db_path))

    assert stats["total"] == 4
    assert stats["evidence_class"]["user_self_report"] == 2
    assert stats["evidence_class"]["user_question"] == 1
    assert stats["reason_code"]["user_default"] == 2
    assert stats["reason_code"]["user_question_lead_or_mark"] == 1
    # user_default hit-rate among classified rows = 2 / 3
    assert stats["user_default_hit_rate"] == pytest.approx(2 / 3)
    assert stats["error_rate"] == pytest.approx(1 / 4)


def test_unknown_status_excluded_from_classified(tmp_path):
    db_path = str(tmp_path / "l1u.db")

    async def _seed_u():
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(_SCHEMA)
            await db.executemany(
                "INSERT INTO fact_events(event_id, evidence_status, evidence_class, "
                "l1_retrieval_scope, metadata_json) VALUES (?, ?, ?, ?, ?)",
                [
                    ("c1", 2, 2, 2, '{"_evidence": {"reason_code": "user_default"}}'),  # classified
                    ("u1", 1, 1, 1, None),  # UNKNOWN status — not classified, not error
                ],
            )
            await db.commit()

    asyncio.run(_seed_u())
    stats = asyncio.run(compute_evidence_stats(db_path))
    assert stats["total"] == 2
    assert stats["classified"] == 1
    assert stats["errors"] == 0
    # hit-rate denominator excludes the UNKNOWN row: 1 user_default / 1 classified
    assert stats["user_default_hit_rate"] == pytest.approx(1.0)
