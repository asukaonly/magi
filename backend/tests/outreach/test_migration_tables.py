import sqlite3


def test_outreach_tables_exist(runtime_paths_with_schema):
    db = runtime_paths_with_schema.channels_db_path
    conn = sqlite3.connect(db)
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()
    assert "outreach_outbox" in names
    assert "outreach_delivery_log" in names
