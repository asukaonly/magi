from __future__ import annotations

import sqlite3

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config


def _target():
    return next(target for target in MIGRATION_TARGETS if target.name == "background_tasks")


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("state", ["attempting", "uncertain", "succeeded", "failed_no_effect"])
def test_effect_ledger_schema_paths_preserve_unresolved_effects(tmp_path, legacy, state):
    path = tmp_path / "effects.db"
    config = _build_config(_target(), path)
    if legacy:
        command.upgrade(config, "v3")
        with sqlite3.connect(path) as connection:
            connection.execute("DROP INDEX idx_tool_effect_attempts_scope")
            connection.execute("DROP INDEX idx_tool_effect_attempts_semantic_state")
            connection.execute("DROP TABLE tool_effect_attempts")
    command.upgrade(config, "v4")
    unresolved = state in {"attempting", "uncertain"}
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO tool_effect_attempts(attempt_id,semantic_key,scope_id,tool_name,replay_policy,arguments_digest,state,started_at,finished_at,updated_at) VALUES ('effect-1','semantic-1','turn:1','file_write','reconcilable','digest',?,1,?,2)",
            (state, None if unresolved else 2),
        )
        before = connection.execute("SELECT * FROM tool_effect_attempts").fetchall()
        for query, index in [
            (
                "SELECT attempt_id FROM tool_effect_attempts WHERE scope_id='turn:1'",
                "idx_tool_effect_attempts_scope",
            ),
            (
                "SELECT attempt_id FROM tool_effect_attempts WHERE semantic_key='semantic-1' AND state='uncertain'",
                "idx_tool_effect_attempts_semantic_state",
            ),
        ]:
            assert any(index in row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query))
    if unresolved:
        with pytest.raises(RuntimeError, match="while outcomes are unresolved"):
            command.downgrade(config, "v3")
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT * FROM tool_effect_attempts").fetchall() == before
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "v4",
            )
    else:
        command.downgrade(config, "v3")
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tool_effect_attempts'"
                ).fetchone()
                is None
            )
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "v3",
            )
