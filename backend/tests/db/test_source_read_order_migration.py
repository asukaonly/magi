"""Existing source revisions retain their browse identities after migration."""
import sqlite3

from magi.db.runner import run_upgrade_database


def test_read_order_adopts_existing_revisions_and_preserves_sequence(tmp_path):
    path = tmp_path / 'sources.db'
    run_upgrade_database('plugin_sources', path, revision='v2')
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO source_connections VALUES ('phone','health',1,0)")
        db.execute("INSERT INTO source_checkpoints VALUES ('phone','health','apple_health',NULL,0)")
        db.execute("INSERT INTO source_versions(connection_id,source_id,object_id,version,operation,digest) VALUES ('phone','health','steps','one','upsert','hash')")
    run_upgrade_database('plugin_sources', path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT read_order FROM source_versions').fetchone() == (1,)
        assert db.execute('SELECT value FROM source_read_sequence').fetchone() == (1,)
        db.execute('DELETE FROM source_versions')
        db.commit()
        db.execute('VACUUM')
        assert db.execute('SELECT value FROM source_read_sequence').fetchone() == (1,)
