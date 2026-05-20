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
# the other migrations.
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
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
