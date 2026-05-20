"""manual_entries.weather_json

Revision ID: 0008_manual_entries_weather
Revises: 0007_manual_entries
Create Date: 2026-05-20

Phase B-1 of the manual-entry feature: an ambient weather chip (☀️/🌧/⛅
+ temperature) gets resolved against Open-Meteo when the entry has — or
can borrow — a lat/lng, and stored back on the row.

A nullable TEXT column is plenty here. The shape stays small (~50B per
row) and we'd rather keep the schema homogeneous with the existing
``attachments_json`` and other "small structured blob" patterns than
break out two extra columns for code + temp.

Schema of the stored JSON:
    {"code": 2, "temp_c": 22.5, "fetched_at": 1716210000}

``code`` is the WMO weather code (0=clear, 1=mainly clear, 2=partly
cloudy, 3=overcast, 45/48=fog, 51/53/55=drizzle, 61/63/65=rain,
71/73/75=snow, 80/81/82=showers, 95/96/99=thunderstorm).
"""

from __future__ import annotations

from alembic import op

revision = "0008_manual_entries_weather"
down_revision = "0007_manual_entries"
branch_labels = None
depends_on = None


# Named SCHEMA_SQL (not UPGRADE_SQL) so the test schema helper —
# which regex-extracts the constant by name — picks it up alongside
# the other migrations on a fresh DB.
SCHEMA_SQL = """
ALTER TABLE manual_entries ADD COLUMN weather_json TEXT;
"""

# SQLite ALTER TABLE DROP COLUMN landed in 3.35 (2021); the project's
# minimum sqlite (Python bundled) is well past that, so the downgrade is
# straightforward.
DROP_SQL = """
ALTER TABLE manual_entries DROP COLUMN weather_json;
"""


def upgrade() -> None:
    """Add weather_json column — defensively.

    During B-1 development the column was hand-applied via a manual
    ALTER before the migration shipped, leaving the dev DB in a state
    where the column existed but alembic_version was still at 0007.
    A naïve `ALTER TABLE ADD COLUMN` then fails on the next boot with
    'duplicate column name'. SQLite has no `ADD COLUMN IF NOT EXISTS`,
    so we introspect PRAGMA table_info and skip the ALTER when the
    column is already present. Either way Alembic records the
    migration as applied, so the next boot is clean.
    """
    conn = op.get_bind().connection
    cursor = conn.execute("PRAGMA table_info(manual_entries)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    if "weather_json" not in existing_columns:
        conn.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
