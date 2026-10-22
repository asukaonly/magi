"""MySQL event facts, side records and durable clear ownership."""

from alembic import op
from sqlalchemy import inspect

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS magi_l1_chunks (
	chunk_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	chunk_id LONGTEXT NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	chunk_index INTEGER NOT NULL, 
	chunk_text LONGTEXT NOT NULL, 
	char_start INTEGER NOT NULL, 
	char_end INTEGER NOT NULL, 
	token_estimate INTEGER NOT NULL, 
	embedding_profile_id LONGTEXT, 
	created_at DOUBLE NOT NULL, 
	updated_at DOUBLE NOT NULL, 
	PRIMARY KEY (chunk_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_chunks_event ON magi_l1_chunks (event_key, chunk_index)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_embeddings (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	embedding_status INTEGER NOT NULL, 
	embedding_profile_id LONGTEXT, 
	embedding_chunk_count INTEGER NOT NULL, 
	last_embedded_at DOUBLE, 
	updated_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_pending_embeddings ON magi_l1_embeddings (embedding_status)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_entities (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	entity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	entity_id LONGTEXT NOT NULL, 
	entity_type LONGTEXT, 
	confidence DOUBLE, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_key, entity_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_entities_entity ON magi_l1_entities (entity_key)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_events (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	dedup_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin, 
	session_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin, 
	user_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin, 
	source_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	turn_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin, 
	event_id LONGTEXT NOT NULL, 
	timestamp DOUBLE NOT NULL, 
	created_at DOUBLE NOT NULL, 
	event_type LONGTEXT NOT NULL, 
	source LONGTEXT NOT NULL, 
	source_item_id LONGTEXT, 
	idempotency_key LONGTEXT, 
	memory_domain INTEGER NOT NULL, 
	cognition_eligible INTEGER NOT NULL, 
	retention_class INTEGER NOT NULL, 
	session_id LONGTEXT, 
	turn_id LONGTEXT, 
	session_seq BIGINT, 
	user_id LONGTEXT, 
	content LONGTEXT NOT NULL, 
	author_type INTEGER NOT NULL, 
	content_type INTEGER NOT NULL, 
	importance_score DOUBLE NOT NULL, 
	media_path LONGTEXT, 
	metadata_json LONGTEXT, 
	deleted_at DOUBLE, 
	evidence_status INTEGER NOT NULL, 
	evidence_class INTEGER NOT NULL, 
	evidence_rule_version INTEGER NOT NULL, 
	l1_retrieval_scope INTEGER NOT NULL, 
	search_text LONGTEXT NOT NULL, 
	PRIMARY KEY (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_deleted ON magi_l1_events (deleted_at)""",
    """CREATE INDEX ix_l1_retention_scan ON magi_l1_events (retention_class, timestamp, event_key)""",
    """CREATE FULLTEXT INDEX ix_l1_search ON magi_l1_events (search_text) WITH PARSER ngram""",
    """CREATE INDEX ix_l1_session_sequence ON magi_l1_events (session_key, session_seq)""",
    """CREATE INDEX ix_l1_source_time ON magi_l1_events (source_key, timestamp)""",
    """CREATE INDEX ix_l1_turn ON magi_l1_events (turn_key)""",
    """CREATE INDEX ix_l1_user_time ON magi_l1_events (user_key, timestamp)""",
    """CREATE UNIQUE INDEX uq_l1_dedup_key ON magi_l1_events (dedup_key)""",
    """CREATE UNIQUE INDEX uq_l1_event_key ON magi_l1_events (event_key)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_facets (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	source_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	facet_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	text_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin, 
	event_id LONGTEXT NOT NULL, 
	source LONGTEXT NOT NULL, 
	facet_name LONGTEXT NOT NULL, 
	text_value LONGTEXT, 
	normalized_text_value LONGTEXT, 
	numeric_value DOUBLE, 
	timestamp_value DOUBLE, 
	json_value LONGTEXT, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_facets_event ON magi_l1_facets (event_key)""",
    """CREATE INDEX ix_l1_facets_lookup ON magi_l1_facets (source_key, facet_key, text_key)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_handoffs (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	available_at DOUBLE NOT NULL, 
	attempt_count INTEGER NOT NULL, 
	last_error LONGTEXT, 
	PRIMARY KEY (event_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_handoff_ready ON magi_l1_handoffs (available_at, created_at)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_payloads (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	content LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_payload_retention ON magi_l1_payloads (created_at)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_profiles (
	profile_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	profile_id LONGTEXT NOT NULL, 
	provider_name LONGTEXT NOT NULL, 
	model_name LONGTEXT NOT NULL, 
	embedding_dim INTEGER, 
	text_builder_version LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (profile_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE TABLE IF NOT EXISTS magi_l1_projected_entities (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	entity_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	entity_id LONGTEXT NOT NULL, 
	entity_type LONGTEXT, 
	confidence DOUBLE, 
	revision BIGINT NOT NULL, 
	lease_token LONGTEXT NOT NULL, 
	attempt_count BIGINT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_key, entity_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE INDEX ix_l1_projected_entity ON magi_l1_projected_entities (entity_key)""",
    """CREATE TABLE IF NOT EXISTS magi_l1_projection_state (
	event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	event_id LONGTEXT NOT NULL, 
	revision BIGINT NOT NULL, 
	lease_token LONGTEXT NOT NULL, 
	attempt_count BIGINT NOT NULL, 
	payload_fingerprint LONGTEXT NOT NULL, 
	applied_at DOUBLE NOT NULL, 
	PRIMARY KEY (event_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE TABLE IF NOT EXISTS magi_l1_sequences (
	session_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	session_id LONGTEXT NOT NULL, 
	next_seq BIGINT NOT NULL, 
	updated_at DOUBLE NOT NULL, 
	PRIMARY KEY (session_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE TABLE IF NOT EXISTS magi_l1_sessions (
	session_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL, 
	session_id LONGTEXT NOT NULL, 
	user_id LONGTEXT NOT NULL, 
	title LONGTEXT NOT NULL, 
	title_overridden INTEGER NOT NULL, 
	summary LONGTEXT NOT NULL, 
	created_at DOUBLE NOT NULL, 
	updated_at DOUBLE NOT NULL, 
	last_message_at DOUBLE, 
	last_user_message_at DOUBLE, 
	last_message_preview LONGTEXT NOT NULL, 
	last_user_message_preview LONGTEXT NOT NULL, 
	message_count BIGINT NOT NULL, 
	workspace_path LONGTEXT, 
	archived_at DOUBLE, 
	deleted_at DOUBLE, 
	PRIMARY KEY (session_key)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
    """CREATE TABLE IF NOT EXISTS magi_l1_state (
	singleton_id INTEGER NOT NULL AUTO_INCREMENT, 
	center_id LONGTEXT, 
	clear_generation BIGINT NOT NULL, 
	updated_at DOUBLE NOT NULL, 
	PRIMARY KEY (singleton_id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_bin""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        if (
            statement.startswith("CREATE INDEX")
            or statement.startswith("CREATE UNIQUE INDEX")
            or statement.startswith("CREATE FULLTEXT INDEX")
        ):
            words = statement.split()
            name = words[words.index("INDEX") + 1]
            table_name = words[words.index("ON") + 1]
            if name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}:
                continue
        op.execute(statement)
    op.execute(
        "INSERT INTO magi_l1_state(singleton_id, clear_generation, updated_at) VALUES (1, 0, 0) ON DUPLICATE KEY UPDATE singleton_id=singleton_id"
    )


def downgrade() -> None:
    raise RuntimeError("Export memory events before changing their storage schema")
