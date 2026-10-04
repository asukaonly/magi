"""Execute temporal clauses against independent boundary records."""

import sqlite3
from types import SimpleNamespace

import pytest

from magi.memory.hybrid_retrieval import temporal
from magi.memory.hybrid_retrieval.models import TemporalContext


def _selected(schema, rows, clause, params):
    with sqlite3.connect(":memory:") as db:
        db.execute(f"CREATE TABLE records ({schema})")
        db.executemany(f"INSERT INTO records VALUES ({','.join('?' for _ in rows[0])})", rows)
        return {
            row[0]
            for row in db.execute("SELECT name FROM records WHERE " + (clause or "1=1"), params)
        }


@pytest.mark.parametrize(
    "context,expected",
    [
        (
            None,
            {
                "current",
                "old",
                "deprecated",
                "expired",
                "future",
                "touch_start",
                "touch_end",
                "expires_at_anchor",
                "deprecated_at_anchor",
            },
        ),
        (
            TemporalContext(mode="none"),
            {
                "current",
                "old",
                "deprecated",
                "expired",
                "future",
                "touch_start",
                "touch_end",
                "expires_at_anchor",
                "deprecated_at_anchor",
            },
        ),
        (TemporalContext(mode="current"), {"current", "old", "future", "touch_start", "touch_end"}),
        (
            TemporalContext(mode="as_of", anchor=150),
            {"current", "old", "deprecated", "expired", "touch_start"},
        ),
        (
            TemporalContext(mode="during", start=100, end=200),
            {
                "current",
                "deprecated",
                "expired",
                "touch_start",
                "touch_end",
                "expires_at_anchor",
                "deprecated_at_anchor",
            },
        ),
    ],
)
def test_knowledge_clause_selects_exact_temporal_records(monkeypatch, context, expected):
    monkeypatch.setattr(temporal, "time", SimpleNamespace(time=lambda: 500.0))
    rows = [
        ("current", 100, 200, None, None, "active"),
        ("old", 10, 90, None, None, "active"),
        ("deprecated", 50, 150, 160, None, "deprecated"),
        ("expired", 50, 150, None, 160, "active"),
        ("future", 201, 300, None, None, "active"),
        ("touch_start", 10, 100, None, None, "active"),
        ("touch_end", 200, 300, None, None, "active"),
        ("expires_at_anchor", 20, 150, None, 150, "active"),
        ("deprecated_at_anchor", 20, 150, 150, None, "deprecated"),
    ]
    clause, params = temporal.build_knowledge_temporal_clause(context)
    assert (
        _selected(
            "name TEXT,first_observed_at REAL,last_observed_at REAL,deprecated_at REAL,expires_at REAL,status TEXT",
            rows,
            clause,
            params,
        )
        == expected
    )


@pytest.mark.parametrize(
    "context,expected",
    [
        (TemporalContext(mode="current"), {"tentative", "corroborated", "stable", "future"}),
        (
            TemporalContext(mode="as_of", anchor=150),
            {"tentative", "corroborated", "stable", "superseded_later", "expires_later"},
        ),
    ],
)
def test_assertion_clause_applies_state_expiry_and_historical_supersession(
    monkeypatch, context, expected
):
    monkeypatch.setattr(temporal, "time", SimpleNamespace(time=lambda: 500.0))
    rows = [
        ("tentative", 100, 200, None, None, "tentative"),
        ("corroborated", 100, 200, None, None, "corroborated"),
        ("stable", 50, 200, None, None, "stable"),
        ("rejected", 100, 200, None, None, "user_rejected"),
        ("superseded_later", 50, 150, 160, None, "superseded"),
        ("expires_later", 50, 150, None, 160, "stable"),
        ("future", 201, 300, None, None, "stable"),
        ("expires_at_anchor", 20, 150, None, 150, "stable"),
        ("superseded_at_anchor", 20, 150, 150, None, "superseded"),
    ]
    clause, params = temporal.build_assertion_temporal_clause(context)
    if context.mode == "as_of":
        # The temporal fragment composes with the retrieval owner's state gate.
        clause = (
            "validation_state IN ('tentative','corroborated','stable','superseded') AND " + clause
        )
    assert (
        _selected(
            "name TEXT,first_inferred_at REAL,last_validated_at REAL,superseded_at REAL,expires_at REAL,validation_state TEXT",
            rows,
            clause,
            params,
        )
        == expected
    )


def test_episode_clause_includes_overlaps_and_both_touching_boundaries():
    rows = [
        ("before", 10, 99),
        ("touch_start", 10, 100),
        ("inside", 125, 175),
        ("covers", 50, 250),
        ("touch_end", 200, 250),
        ("after", 201, 250),
    ]
    clause, params = temporal.build_episode_temporal_clause(
        TemporalContext(mode="during", start=100, end=200)
    )
    assert _selected("name TEXT,time_start REAL,time_end REAL", rows, clause, params) == {
        "touch_start",
        "inside",
        "covers",
        "touch_end",
    }


@pytest.mark.parametrize(
    "context,first,last,expected",
    [
        (None, None, None, 1.0),
        (TemporalContext(mode="none"), 600, 700, 1.0),
        (TemporalContext(mode="current"), None, None, 0.5),
        (TemporalContext(mode="current"), None, 10000000 - 3600, 1.0),
        (TemporalContext(mode="current"), None, 10000000 - 10 * 86400, 0.8),
        (TemporalContext(mode="current"), None, 10000000 - 60 * 86400, 0.6),
        (TemporalContext(mode="current"), None, 10000000 - 200 * 86400, 0.3),
        (TemporalContext(mode="as_of", anchor=150), None, None, 0.5),
        (TemporalContext(mode="as_of", anchor=150), 150, 200, 1.0),
        (TemporalContext(mode="as_of", anchor=150), 151, 200, 0.0),
        (TemporalContext(mode="during", start=100, end=200), 100, 200, 1.0),
        (TemporalContext(mode="during", start=100, end=200), 150, 250, 0.5),
        (TemporalContext(mode="during", start=100, end=200), 125, 175, 0.5),
        (TemporalContext(mode="during", start=100, end=200), 10, 99, 0.0),
        (TemporalContext(mode="during", start=100, end=200), 201, 300, 0.0),
        (TemporalContext(mode="during", start=100, end=200), 10, 100, 0.0),
        (TemporalContext(mode="during", start=100, end=200), 200, 300, 0.0),
        (TemporalContext(mode="during", start=100, end=200), None, 150, 0.5),
        (TemporalContext(mode="during", start=100, end=100), 50, 150, 1.0),
    ],
)
def test_temporal_scores_distinguish_recency_overlap_and_missing_time(
    monkeypatch, context, first, last, expected
):
    monkeypatch.setattr(temporal, "time", SimpleNamespace(time=lambda: 10000000.0))
    assert temporal.compute_temporal_score(
        context, first_observed=first, last_observed=last
    ) == pytest.approx(expected)
