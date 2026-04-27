"""Schema migration helpers for the L2 cognition store."""

from __future__ import annotations

import aiosqlite


class L2StoreMigrationMixin:
    """Backfill older L2 schema variants to the current store shape."""

    async def _ensure_tom_assertion_schema(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(tom_trait_assertions)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        required_columns = {
            "assertion_id",
            "entity_id",
            "entity_type",
            "trait_family",
            "trait_name",
            "trait_value",
            "confidence_score",
            "evidence_events",
            "volatility_index",
            "source_domain",
            "inference_depth",
            "validation_state",
            "first_inferred_at",
            "last_validated_at",
            "target_entity_id",
            "target_entity_type",
            "target_scope",
            "temporal_scope",
            "decay_policy",
            "decay_anchor_at",
            "context_ref_id",
            "expires_at",
            "created_at",
            "updated_at",
        }
        if required_columns.issubset(existing_columns):
            if "user_feedback" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN user_feedback TEXT")
            if "user_feedback_at" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN user_feedback_at REAL")

            if "status" not in existing_columns:
                await db.execute(
                    "ALTER TABLE tom_trait_assertions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                )
            if "superseded_by" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN superseded_by TEXT")
            if "superseded_at" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN superseded_at REAL")
            if "privacy_scope" not in existing_columns:
                await db.execute(
                    "ALTER TABLE tom_trait_assertions ADD COLUMN privacy_scope TEXT NOT NULL DEFAULT 'private'"
                )

            if "memory_subdomain" not in existing_columns:
                await db.execute(
                    "ALTER TABLE tom_trait_assertions ADD COLUMN memory_subdomain TEXT NOT NULL DEFAULT 'state'"
                )
                await db.execute(
                    """
                    UPDATE tom_trait_assertions SET memory_subdomain = 'semantic'
                    WHERE temporal_scope IN ('persistent', 'stable', '')
                      AND (decay_policy IS NULL OR decay_policy IN ('none', 'evidence_only', ''))
                    """
                )

            if "status" not in existing_columns:
                await db.execute(
                    """
                    UPDATE tom_trait_assertions SET status = CASE
                        WHEN validation_state = 'stable' THEN 'stable'
                        WHEN validation_state = 'corroborated' THEN 'corroborated'
                        WHEN validation_state = 'tentative' THEN 'tentative'
                        WHEN validation_state = 'contradicted' THEN 'contradicted'
                        WHEN validation_state = 'expired' THEN 'expired'
                        WHEN validation_state = 'user_rejected' THEN 'user_rejected'
                        ELSE 'active'
                    END
                    """
                )

            async with db.execute("PRAGMA index_list(tom_trait_assertions)") as cursor:
                indexes = await cursor.fetchall()
            has_old_unique = any(str(idx["origin"]) == "u" for idx in indexes)
            if has_old_unique:
                await self._recreate_assertions_without_unique(db)

            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tom_assertions_active_key
                    ON tom_trait_assertions(entity_id, entity_type, trait_name, target_entity_id, status)
                    WHERE status NOT IN ('superseded', 'archived', 'expired', 'user_rejected')
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tom_assertions_privacy_scope
                    ON tom_trait_assertions(privacy_scope)
                """
            )
            return

        await db.executescript(
            """
            ALTER TABLE tom_trait_assertions RENAME TO tom_trait_assertions_legacy;
            CREATE TABLE tom_trait_assertions (
                assertion_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                trait_family TEXT NOT NULL,
                trait_name TEXT NOT NULL,
                trait_value TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                evidence_events TEXT NOT NULL,
                volatility_index REAL NOT NULL,
                source_domain TEXT NOT NULL,
                inference_depth TEXT NOT NULL,
                validation_state TEXT NOT NULL,
                first_inferred_at REAL NOT NULL,
                last_validated_at REAL NOT NULL,
                target_entity_id TEXT NOT NULL DEFAULT '',
                target_entity_type TEXT NOT NULL DEFAULT '',
                target_scope TEXT NOT NULL DEFAULT 'global',
                temporal_scope TEXT NOT NULL DEFAULT 'session',
                decay_policy TEXT,
                decay_anchor_at REAL,
                context_ref_id TEXT NOT NULL DEFAULT '',
                expires_at REAL,
                user_feedback TEXT,
                user_feedback_at REAL,
                status TEXT NOT NULL DEFAULT 'active',
                superseded_by TEXT,
                superseded_at REAL,
                privacy_scope TEXT NOT NULL DEFAULT 'private',
                memory_subdomain TEXT NOT NULL DEFAULT 'state',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        await db.execute(
            """
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain, inference_depth,
                validation_state, first_inferred_at, last_validated_at, target_entity_id,
                target_entity_type, target_scope, temporal_scope, decay_policy, decay_anchor_at,
                context_ref_id, expires_at, status, privacy_scope, memory_subdomain, created_at, updated_at
            )
            SELECT
                assertion_id,
                entity_id,
                entity_type,
                CASE
                    WHEN trait_name = 'stress_level' THEN 'stress'
                    WHEN trait_name IN ('mood', 'annoyance', 'irritation', 'frustration') THEN 'mood'
                    WHEN trait_name = 'engagement' THEN 'engagement'
                    WHEN trait_name LIKE 'trigger.%' THEN 'trigger'
                    WHEN trait_name IN ('taste_profile', 'taste_preference') THEN 'taste_profile'
                    WHEN trait_name LIKE 'preference.%' THEN 'preference_profile'
                    ELSE 'preference_profile'
                END,
                trait_name,
                trait_value,
                confidence_score,
                evidence_events,
                volatility_index,
                source_domain,
                inference_depth,
                validation_state,
                first_inferred_at,
                last_validated_at,
                '',
                '',
                'global',
                CASE
                    WHEN trait_name IN ('annoyance', 'irritation', 'frustration') THEN 'momentary'
                    WHEN trait_name = 'stress_level' THEN 'daily'
                    WHEN trait_name IN ('mood', 'engagement') THEN 'session'
                    ELSE 'stable'
                END,
                CASE
                    WHEN trait_name IN ('annoyance', 'irritation', 'frustration') THEN 'fast_decay'
                    WHEN trait_name = 'stress_level' THEN 'time_window'
                    WHEN trait_name IN ('mood', 'engagement') THEN 'session_decay'
                    ELSE 'evidence_only'
                END,
                last_validated_at,
                '',
                expires_at,
                CASE
                    WHEN validation_state = 'stable' THEN 'stable'
                    WHEN validation_state = 'corroborated' THEN 'corroborated'
                    WHEN validation_state = 'tentative' THEN 'tentative'
                    WHEN validation_state = 'contradicted' THEN 'contradicted'
                    WHEN validation_state = 'expired' THEN 'expired'
                    WHEN validation_state = 'user_rejected' THEN 'user_rejected'
                    ELSE 'active'
                END,
                'private',
                CASE
                    WHEN trait_name IN ('annoyance', 'irritation', 'frustration', 'mood', 'engagement', 'stress_level') THEN 'state'
                    ELSE 'semantic'
                END,
                created_at,
                updated_at
            FROM tom_trait_assertions_legacy
            """
        )
        await db.execute("DROP TABLE tom_trait_assertions_legacy")

    async def _recreate_assertions_without_unique(self, db: aiosqlite.Connection) -> None:
        """Drop the old assertion UNIQUE constraint by recreating the table."""
        await db.executescript(
            """
            ALTER TABLE tom_trait_assertions RENAME TO _tom_assertions_uniq_mig;
            CREATE TABLE tom_trait_assertions (
                assertion_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                trait_family TEXT NOT NULL,
                trait_name TEXT NOT NULL,
                trait_value TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                evidence_events TEXT NOT NULL,
                volatility_index REAL NOT NULL,
                source_domain TEXT NOT NULL,
                inference_depth TEXT NOT NULL,
                validation_state TEXT NOT NULL,
                first_inferred_at REAL NOT NULL,
                last_validated_at REAL NOT NULL,
                target_entity_id TEXT NOT NULL DEFAULT '',
                target_entity_type TEXT NOT NULL DEFAULT '',
                target_scope TEXT NOT NULL DEFAULT 'global',
                temporal_scope TEXT NOT NULL DEFAULT 'session',
                decay_policy TEXT,
                decay_anchor_at REAL,
                context_ref_id TEXT NOT NULL DEFAULT '',
                expires_at REAL,
                user_feedback TEXT,
                user_feedback_at REAL,
                status TEXT NOT NULL DEFAULT 'active',
                superseded_by TEXT,
                superseded_at REAL,
                privacy_scope TEXT NOT NULL DEFAULT 'private',
                memory_subdomain TEXT NOT NULL DEFAULT 'state',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            INSERT INTO tom_trait_assertions
                SELECT assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                       confidence_score, evidence_events, volatility_index, source_domain,
                       inference_depth, validation_state, first_inferred_at, last_validated_at,
                       target_entity_id, target_entity_type, target_scope, temporal_scope,
                       decay_policy, decay_anchor_at, context_ref_id, expires_at,
                       user_feedback, user_feedback_at,
                       status, superseded_by, superseded_at, privacy_scope,
                       COALESCE(memory_subdomain, 'state'),
                       created_at, updated_at
                FROM _tom_assertions_uniq_mig;
            DROP TABLE _tom_assertions_uniq_mig;
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tom_assertions_entity_updated
                ON tom_trait_assertions(entity_id, entity_type, updated_at DESC)
            """
        )

    async def _ensure_tom_snapshot_schema(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(tom_snapshots)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        required_columns = {
            "core_traits_history": "TEXT",
            "preferences_history": "TEXT",
            "relationship_history": "TEXT",
            "last_evolution_at": "REAL",
            "active_record_ids": "TEXT",
            "superseded_record_ids": "TEXT",
            "emerging_signals": "TEXT",
            "mood_trajectory": "TEXT",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            await db.execute(f"ALTER TABLE tom_snapshots ADD COLUMN {column_name} {column_type}")
