"""Round 5 #7: when knowledge_graph still has many rows with NULL
evidence_class, the hybrid retrieval service should emit a one-shot
WARNING pointing the operator to the backfill script. The check must
tolerate missing tables / missing DB without breaking startup.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from magi.memory.hybrid_retrieval.service import (
    _EVIDENCE_CLASS_STALENESS_THRESHOLD,
    _EVIDENCE_CLASS_WARNED_PATHS,
    _warn_if_evidence_class_stale,
)


@pytest.fixture(autouse=True)
def _reset_warned_paths():
    """Each test gets a fresh warn-once set so order independence holds."""
    snapshot = set(_EVIDENCE_CLASS_WARNED_PATHS)
    _EVIDENCE_CLASS_WARNED_PATHS.clear()
    yield
    _EVIDENCE_CLASS_WARNED_PATHS.clear()
    _EVIDENCE_CLASS_WARNED_PATHS.update(snapshot)


def _make_kg_db(path: Path, null_rows: int, populated_rows: int) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE knowledge_graph "
            "(triple_id TEXT PRIMARY KEY, evidence_class TEXT)"
        )
        for i in range(null_rows):
            conn.execute(
                "INSERT INTO knowledge_graph (triple_id, evidence_class) VALUES (?, NULL)",
                (f"null-{i}",),
            )
        for i in range(populated_rows):
            conn.execute(
                "INSERT INTO knowledge_graph (triple_id, evidence_class) VALUES (?, ?)",
                (f"ok-{i}", "USER_SELF_REPORT"),
            )


def test_warns_when_null_ratio_above_threshold(tmp_path, caplog) -> None:
    db = tmp_path / "kg.db"
    _make_kg_db(db, null_rows=80, populated_rows=20)  # 80% NULL → above 10%
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(str(db))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("evidence_class" in m and "backfill_kg_evidence_class" in m for m in msgs), msgs


def test_silent_when_null_ratio_below_threshold(tmp_path, caplog) -> None:
    db = tmp_path / "kg.db"
    _make_kg_db(db, null_rows=5, populated_rows=95)  # 5% NULL → below 10%
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(str(db))
    assert not any("evidence_class" in r.getMessage() for r in caplog.records)


def test_silent_when_table_missing(tmp_path, caplog) -> None:
    db = tmp_path / "kg.db"
    # touch the DB but don't create the table
    sqlite3.connect(db).close()
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(str(db))
    assert not any("evidence_class" in r.getMessage() for r in caplog.records)


def test_silent_when_db_path_none(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(None)
    assert not caplog.records


def test_silent_when_table_empty(tmp_path, caplog) -> None:
    db = tmp_path / "kg.db"
    _make_kg_db(db, null_rows=0, populated_rows=0)
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(str(db))
    assert not any("evidence_class" in r.getMessage() for r in caplog.records)


def test_warn_once_per_db_path(tmp_path, caplog) -> None:
    db = tmp_path / "kg.db"
    _make_kg_db(db, null_rows=50, populated_rows=50)
    with caplog.at_level(logging.WARNING, logger="magi.memory.hybrid_retrieval.service"):
        _warn_if_evidence_class_stale(str(db))
        _warn_if_evidence_class_stale(str(db))
        _warn_if_evidence_class_stale(str(db))
    warns = [r for r in caplog.records if "evidence_class" in r.getMessage()]
    assert len(warns) == 1, f"expected single warning, got {len(warns)}"


def test_threshold_is_positive_fraction() -> None:
    """Sanity guard: misconfiguring the constant to >= 1.0 would silence
    even fully-NULL databases. Pin the documented value."""
    assert 0.0 < _EVIDENCE_CLASS_STALENESS_THRESHOLD < 1.0
