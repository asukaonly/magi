"""Use the connection supplied by the MySQL lifecycle owner."""

from alembic import context

connection = context.config.attributes["connection"]
context.configure(connection=connection, version_table="magi_l1_version")
with context.begin_transaction():
    context.run_migrations()
