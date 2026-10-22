"""MySQL L1 schema expressions; migrations alone create these tables."""

from sqlalchemy import BigInteger, Column, Double, Index, Integer, MetaData, Table
from sqlalchemy.dialects.mysql import CHAR, LONGTEXT

metadata = MetaData()


def key(name: str, *, primary: bool = False, nullable: bool = False) -> Column:
    return Column(
        name,
        CHAR(64, charset="ascii", collation="ascii_bin"),
        primary_key=primary,
        nullable=nullable,
    )


def string(name: str, *, nullable: bool = True) -> Column:
    return Column(name, LONGTEXT, nullable=nullable)


def table(name: str, *columns: Column) -> Table:
    return Table(
        "magi_l1_" + name,
        metadata,
        *columns,
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_bin",
    )


state = table(
    "state",
    Column("singleton_id", Integer, primary_key=True),
    string("center_id"),
    Column("clear_generation", BigInteger, nullable=False),
    Column("event_sequence", BigInteger, nullable=False),
    Column("updated_at", Double, nullable=False),
)
events = table(
    "events",
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    key("event_key"),
    key("dedup_key", nullable=True),
    key("session_key", nullable=True),
    key("user_key", nullable=True),
    key("source_key"),
    key("turn_key", nullable=True),
    string("event_id", nullable=False),
    Column("timestamp", Double, nullable=False),
    Column("created_at", Double, nullable=False),
    string("event_type", nullable=False),
    string("source", nullable=False),
    string("source_item_id"),
    string("idempotency_key"),
    Column("memory_domain", Integer, nullable=False),
    Column("cognition_eligible", Integer, nullable=False),
    Column("retention_class", Integer, nullable=False),
    string("session_id"),
    string("turn_id"),
    Column("session_seq", BigInteger),
    string("user_id"),
    string("content", nullable=False),
    Column("author_type", Integer, nullable=False),
    Column("content_type", Integer, nullable=False),
    Column("importance_score", Double, nullable=False),
    string("media_path"),
    string("metadata_json"),
    Column("deleted_at", Double),
    Column("evidence_status", Integer, nullable=False),
    Column("evidence_class", Integer, nullable=False),
    Column("evidence_rule_version", Integer, nullable=False),
    Column("l1_retrieval_scope", Integer, nullable=False),
    string("search_text", nullable=False),
)
Index("uq_l1_event_key", events.c.event_key, unique=True)
Index("uq_l1_dedup_key", events.c.dedup_key, unique=True)
Index("ix_l1_session_sequence", events.c.session_key, events.c.session_seq)
Index("ix_l1_user_time", events.c.user_key, events.c.timestamp)
Index("ix_l1_source_time", events.c.source_key, events.c.timestamp)
Index("ix_l1_turn", events.c.turn_key)
Index("ix_l1_retention_scan", events.c.retention_class, events.c.timestamp, events.c.event_key)
Index("ix_l1_deleted", events.c.deleted_at)
Index("ix_l1_search", events.c.search_text, mysql_prefix="FULLTEXT", mysql_with_parser="ngram")
sequences = table(
    "sequences",
    key("session_key", primary=True),
    string("session_id", nullable=False),
    Column("next_seq", BigInteger, nullable=False),
    Column("updated_at", Double, nullable=False),
)
embeddings = table(
    "embeddings",
    key("event_key", primary=True),
    string("event_id", nullable=False),
    Column("embedding_status", Integer, nullable=False),
    string("embedding_profile_id"),
    Column("embedding_chunk_count", Integer, nullable=False),
    Column("last_embedded_at", Double),
    Column("updated_at", Double, nullable=False),
)
Index("ix_l1_pending_embeddings", embeddings.c.embedding_status)
payloads = table(
    "payloads",
    key("event_key", primary=True),
    string("event_id", nullable=False),
    string("content", nullable=False),
    Column("created_at", Double, nullable=False),
)
Index("ix_l1_payload_retention", payloads.c.created_at)
handoffs = table(
    "handoffs",
    key("event_key", primary=True),
    string("event_id", nullable=False),
    Column("created_at", Double, nullable=False),
    Column("available_at", Double, nullable=False),
    Column("attempt_count", Integer, nullable=False),
    string("last_error"),
)
Index("ix_l1_handoff_ready", handoffs.c.available_at, handoffs.c.created_at)
facets = table(
    "facets",
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    key("event_key"),
    key("source_key"),
    key("facet_key"),
    key("text_key", nullable=True),
    string("event_id", nullable=False),
    string("source", nullable=False),
    string("facet_name", nullable=False),
    string("text_value"),
    string("normalized_text_value"),
    Column("numeric_value", Double),
    Column("timestamp_value", Double),
    string("json_value"),
    Column("created_at", Double, nullable=False),
)
Index("ix_l1_facets_event", facets.c.event_key)
Index("ix_l1_facets_lookup", facets.c.source_key, facets.c.facet_key, facets.c.text_key)
profiles = table(
    "profiles",
    key("profile_key", primary=True),
    string("profile_id", nullable=False),
    string("provider_name", nullable=False),
    string("model_name", nullable=False),
    Column("embedding_dim", Integer),
    string("text_builder_version", nullable=False),
    Column("created_at", Double, nullable=False),
)
chunks = table(
    "chunks",
    key("chunk_key", primary=True),
    key("event_key"),
    string("chunk_id", nullable=False),
    string("event_id", nullable=False),
    Column("chunk_index", Integer, nullable=False),
    string("chunk_text", nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("token_estimate", Integer, nullable=False),
    string("embedding_profile_id"),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
)
Index("ix_l1_chunks_event", chunks.c.event_key, chunks.c.chunk_index)
entities = table(
    "entities",
    key("event_key", primary=True),
    key("entity_key", primary=True),
    string("event_id", nullable=False),
    string("entity_id", nullable=False),
    string("entity_type"),
    Column("confidence", Double),
    Column("created_at", Double, nullable=False),
)
Index("ix_l1_entities_entity", entities.c.entity_key)
projection_state = table(
    "projection_state",
    key("event_key", primary=True),
    string("event_id", nullable=False),
    Column("revision", BigInteger, nullable=False),
    string("lease_token", nullable=False),
    Column("attempt_count", BigInteger, nullable=False),
    string("payload_fingerprint", nullable=False),
    Column("applied_at", Double, nullable=False),
)
projected_entities = table(
    "projected_entities",
    key("event_key", primary=True),
    key("entity_key", primary=True),
    string("event_id", nullable=False),
    string("entity_id", nullable=False),
    string("entity_type"),
    Column("confidence", Double),
    Column("revision", BigInteger, nullable=False),
    string("lease_token", nullable=False),
    Column("attempt_count", BigInteger, nullable=False),
    Column("created_at", Double, nullable=False),
)
Index("ix_l1_projected_entity", projected_entities.c.entity_key)
sessions = table(
    "sessions",
    key("session_key", primary=True),
    string("session_id", nullable=False),
    string("user_id", nullable=False),
    string("title", nullable=False),
    Column("title_overridden", Integer, nullable=False),
    string("summary", nullable=False),
    Column("created_at", Double, nullable=False),
    Column("updated_at", Double, nullable=False),
    Column("last_message_at", Double),
    Column("last_user_message_at", Double),
    string("last_message_preview", nullable=False),
    string("last_user_message_preview", nullable=False),
    Column("message_count", BigInteger, nullable=False),
    string("workspace_path"),
    Column("archived_at", Double),
    Column("deleted_at", Double),
)
