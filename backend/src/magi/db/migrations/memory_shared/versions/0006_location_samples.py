"""location samples + geocode cache

Revision ID: 0006_location_samples
Revises: 0005_daily_mood_aggregate
Create Date: 2026-05-20

Tables for the LocationResolver pipeline:

  location_samples       per-source positional observations (photo EXIF,
                         WiFi-scan-resolved coords, IP-geo city). Each row
                         carries timestamp + lat/lng + accuracy + already-
                         reverse-geocoded labels (city/region/country) so
                         the resolver doesn't need to network-hit on read.

  place_geocode_cache    Nominatim / Mozilla reverse-lookup cache keyed by
                         a 4-decimal grid (~10m) of lat/lng. Spares us the
                         1 req/sec rate limit on Nominatim for places we've
                         already seen.

  place_labels           User-overridable display labels for clustered
                         locations ("家", "公司"). Optional in v1 — schema
                         present so the resolver and UI can grow into it
                         without another migration.
"""

from __future__ import annotations

from alembic import op

revision = "0006_location_samples"
down_revision = "0005_daily_mood_aggregate"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS location_samples (
    sample_id      TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    sampled_at     REAL NOT NULL,
    lat            REAL,
    lng            REAL,
    accuracy_m     REAL,
    city           TEXT,
    region         TEXT,
    country        TEXT,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    created_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_loc_samples_time
    ON location_samples(sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_loc_samples_source_time
    ON location_samples(source, sampled_at DESC);

CREATE TABLE IF NOT EXISTS place_geocode_cache (
    grid_key   TEXT PRIMARY KEY,
    city       TEXT,
    region     TEXT,
    country    TEXT,
    poi_name   TEXT,
    cached_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS place_labels (
    label_id    TEXT PRIMARY KEY,
    center_lat  REAL NOT NULL,
    center_lng  REAL NOT NULL,
    radius_m    REAL NOT NULL DEFAULT 100.0,
    user_label  TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_loc_samples_source_time;
DROP INDEX IF EXISTS idx_loc_samples_time;
DROP TABLE IF EXISTS place_labels;
DROP TABLE IF EXISTS place_geocode_cache;
DROP TABLE IF EXISTS location_samples;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
