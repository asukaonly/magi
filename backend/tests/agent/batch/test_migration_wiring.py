from magi.db.runner import MIGRATION_TARGETS


def test_batch_migration_target_registered():
    names = {t.name for t in MIGRATION_TARGETS}
    assert "batch" in names


def test_batch_db_path_property_exists():
    from magi.utils.runtime import RuntimePaths

    assert hasattr(RuntimePaths, "batch_db_path")


def test_batch_migration_creates_tables(tmp_path):
    """Run the real alembic baseline against a temp DB and assert the
    manifest tables exist — covers the migration itself, not just registration."""
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db = tmp_path / "batch.db"
    cfg = Config()
    cfg.set_main_option("script_location", "src/magi/db/migrations/batch")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    cfg.set_main_option("version_path_separator", "os")
    command.upgrade(cfg, "head")

    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "batch_job" in tables
    assert "batch_item" in tables
