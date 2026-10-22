"""Use the connection supplied by the MySQL storage owner."""
from alembic import context
connection = context.config.attributes["connection"]
context.configure(connection=connection, version_table="magi_chat_version")
with context.begin_transaction():
    context.run_migrations()
