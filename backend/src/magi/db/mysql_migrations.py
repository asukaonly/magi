"""Run explicit MySQL migration chains before assembling repositories."""

from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from .mysql import MysqlDatabase


async def upgrade_mysql_channels(database: MysqlDatabase) -> None:
    """Upgrade the channel owner while holding a connection-scoped migration lock."""
    async with database.transaction() as connection:
        lock_name = str(
            (
                await connection.execute(
                    text("SELECT CONCAT('magi-migrations-', LEFT(SHA2(DATABASE(),256),40))")
                )
            ).scalar_one()
        )
        acquired = (
            await connection.execute(text("SELECT GET_LOCK(:name, 10)"), {"name": lock_name})
        ).scalar_one()
        if acquired != 1:
            raise RuntimeError("MySQL schema migration is already in progress")
        try:

            def migrate(sync_connection: Connection) -> None:
                config = Config()
                config.set_main_option(
                    "script_location", str(Path(__file__).parent / "migrations/mysql_channels")
                )
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
            await connection.commit()
        finally:
            await connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock_name})
