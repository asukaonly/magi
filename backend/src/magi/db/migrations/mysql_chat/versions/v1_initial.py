"""Native MySQL chat schema, ownership, guards and read revisions."""
from alembic import op
revision = "mysql_chat_v1"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = [
    """CREATE TABLE magi_chat_owner (
    slot TINYINT NOT NULL PRIMARY KEY CHECK (slot=1),
    center_id LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_assistant_memory_outbox` (
    `canonical_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `content_text` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `state` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('pending'),
    `attempt_count` BIGINT NOT NULL DEFAULT (0),
    `next_attempt_at_ms` BIGINT NOT NULL DEFAULT (0),
    `lease_token` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `lease_expires_at_ms` BIGINT,
    `last_error` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_assistant_memory_outbox_session` (`session_id`(64), `canonical_message_id`(64)),
    KEY `idx_chat_assistant_memory_outbox_ready` (`state`(64), `next_attempt_at_ms`, `lease_expires_at_ms`, `created_at_ms`, `canonical_message_id`(64)),
    CONSTRAINT `ck_assistant_memory_outbox_0` CHECK (state IN ('pending', 'claimed')),
    CONSTRAINT `ck_assistant_memory_outbox_1` CHECK (attempt_count >= 0),
    CONSTRAINT `ck_assistant_memory_outbox_2` CHECK (
        (state = 'pending' AND lease_token IS NULL AND lease_expires_at_ms IS NULL)
        OR (state = 'claimed' AND lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
    )
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_attachments` (
    `attachment_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `original_name` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `mime_type` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('application/octet-stream'),
    `size_bytes` BIGINT NOT NULL DEFAULT (0),
    `storage_rel_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `sha256` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_attachments_message_id` (`message_id`(64)),
    KEY `idx_chat_attachments_session_created` (`session_id`(64), `created_at_ms`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_cleared_message_scopes` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `cleared_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_cleared_session_scopes` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `cleared_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_code_delegation_artifacts` (
    `workspace_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `delegation_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_code_delegation_artifacts_scope` (`session_id`(64), `turn_id`(64), `delegation_id`(64))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_context_summaries` (
    `summary_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `parent_summary_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `status` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('building'),
    `summary_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `persona_scope` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `covered_from_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `covered_to_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `first_kept_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `covered_to_sequence_no` BIGINT,
    `session_origin` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `summary_text` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `prompt_profile` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('general_chat'),
    `model_provider` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `model_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `token_count_before` BIGINT,
    `token_count_after` BIGINT,
    `quality_status` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `created_at_ms` BIGINT NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_context_summaries_frontier` (`session_id`(64), `summary_kind`(64), `persona_scope`(64), `covered_to_sequence_no`),
    KEY `idx_chat_context_summaries_session_status` (`session_id`(64), `status`(64), `updated_at_ms`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_context_usage_snapshots` (
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `used_tokens` BIGINT NOT NULL,
    `context_window` BIGINT NOT NULL,
    `input_capacity` BIGINT NOT NULL,
    `compaction_threshold` BIGINT NOT NULL,
    `measurement` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `model_provider` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `model_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_context_usage_session_updated` (`session_id`(64), `updated_at_ms`, `turn_id`(64)),
    CONSTRAINT `ck_context_usage_snapshots_0` CHECK (used_tokens > 0),
    CONSTRAINT `ck_context_usage_snapshots_1` CHECK (context_window > 0),
    CONSTRAINT `ck_context_usage_snapshots_2` CHECK (input_capacity > 0),
    CONSTRAINT `ck_context_usage_snapshots_3` CHECK (compaction_threshold > 0),
    CONSTRAINT `ck_context_usage_snapshots_4` CHECK (measurement IN ('actual', 'estimated'))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_global_clear_intent` (
    `intent_key` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `requested_at_ms` BIGINT NOT NULL,
    `session_count` BIGINT NOT NULL DEFAULT (0),
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    CONSTRAINT `ck_global_clear_intent_0` CHECK (intent_key = 'global'),
    CONSTRAINT `ck_global_clear_intent_1` CHECK (session_count >= 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_message_asset_refs` (
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `asset_key` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `storage_rel_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `asset_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_message_asset_refs_asset_key` (`asset_key`(64), `message_id`(64))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_message_code_delegation_refs` (
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `delegation_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `workspace_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_message_code_delegation_scope` (`workspace_path`(64), `session_id`(64), `delegation_id`(64), `message_id`(64))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_messages` (
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `role` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `message_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `content_text` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `payload_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('{}'),
    `is_final` BIGINT NOT NULL DEFAULT (1),
    `is_visible` BIGINT NOT NULL DEFAULT (1),
    `created_at_ms` BIGINT NOT NULL,
    `sequence_no` BIGINT NOT NULL,
    `replaces_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `replaced_by_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `persona_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `reply_to_message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `label_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_messages_turn_page` (`user_id`(64), `session_id`(64), `turn_id`(64), `created_at_ms`, `sequence_no`, `message_id`(64)),
    KEY `idx_chat_messages_page` (`user_id`(64), `session_id`(64), `created_at_ms`, `sequence_no`, `message_id`(64)),
    KEY `idx_chat_messages_turn_sequence` (`turn_id`(64), `sequence_no`),
    KEY `idx_chat_messages_session_created` (`session_id`(64), `created_at_ms`, `sequence_no`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_boundaries` (
    `boundary_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL,
    `boundary_no` BIGINT NOT NULL,
    `surface_revision` BIGINT NOT NULL,
    `epoch_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `boundary_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `step_index` BIGINT,
    `request_options_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('{}'),
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_model_context_boundaries_turn` (`session_id`(64), `turn_id`(64), `boundary_no`),
    `__unique_1` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') IS NULL OR `generation` IS NULL OR `boundary_no` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(`generation`), ':', HEX(`boundary_no`)),256) END) STORED,
    UNIQUE KEY `__unique_1` (`__unique_1`),
    CONSTRAINT `ck_model_context_boundaries_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_boundaries_1` CHECK (boundary_no > 0),
    CONSTRAINT `ck_model_context_boundaries_2` CHECK (surface_revision >= 0),
    CONSTRAINT `ck_model_context_boundaries_3` CHECK (step_index IS NULL OR step_index >= 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_epochs` (
    `epoch_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL,
    `system_hash` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `system_prompt` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `tools_hash` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `tools_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    `__unique_0` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') IS NULL OR `generation` IS NULL OR `system_hash` IS NULL OR `tools_hash` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(`generation`), ':', HEX(`system_hash`), ':', HEX(`tools_hash`)),256) END) STORED,
    UNIQUE KEY `__unique_0` (`__unique_0`),
    CONSTRAINT `ck_model_context_epochs_0` CHECK (generation > 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_events` (
    `event_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL,
    `sequence_no` BIGINT NOT NULL,
    `operation` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `item_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `item_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `step_index` BIGINT,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_model_context_events_turn` (`session_id`(64), `turn_id`(64), `sequence_no`),
    KEY `idx_chat_model_context_events_session_sequence` (`session_id`(64), `generation`, `sequence_no`),
    `__unique_2` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') IS NULL OR `generation` IS NULL OR `sequence_no` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(`generation`), ':', HEX(`sequence_no`)),256) END) STORED,
    UNIQUE KEY `__unique_2` (`__unique_2`),
    CONSTRAINT `ck_model_context_events_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_events_1` CHECK (sequence_no > 0),
    CONSTRAINT `ck_model_context_events_2` CHECK (step_index IS NULL OR step_index >= 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_heads` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL DEFAULT (1),
    `revision` BIGINT NOT NULL DEFAULT (0),
    `accepted_revision` BIGINT NOT NULL DEFAULT (0),
    `last_sequence_no` BIGINT NOT NULL DEFAULT (0),
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    CONSTRAINT `ck_model_context_heads_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_heads_1` CHECK (revision >= 0),
    CONSTRAINT `ck_model_context_heads_2` CHECK (accepted_revision >= 0),
    CONSTRAINT `ck_model_context_heads_3` CHECK (last_sequence_no >= 0),
    CONSTRAINT `ck_model_context_heads_4` CHECK (accepted_revision <= revision)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_revisions` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL,
    `revision` BIGINT NOT NULL,
    `parent_revision` BIGINT NOT NULL,
    `branch_kind` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `item_count` BIGINT NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    CONSTRAINT `ck_model_context_revisions_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_revisions_1` CHECK (revision > 0),
    CONSTRAINT `ck_model_context_revisions_2` CHECK (parent_revision >= 0),
    CONSTRAINT `ck_model_context_revisions_3` CHECK (branch_kind IN ('accepted', 'working')),
    CONSTRAINT `ck_model_context_revisions_4` CHECK (item_count >= 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_run_heads` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `generation` BIGINT NOT NULL,
    `base_revision` BIGINT NOT NULL,
    `working_revision` BIGINT NOT NULL,
    `status` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_model_context_run_heads_status` (`session_id`(64), `status`(64), `updated_at_ms`),
    CONSTRAINT `ck_model_context_run_heads_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_run_heads_1` CHECK (base_revision >= 0),
    CONSTRAINT `ck_model_context_run_heads_2` CHECK (working_revision >= 0),
    CONSTRAINT `ck_model_context_run_heads_3` CHECK (status IN ('active', 'accepted', 'abandoned')),
    CONSTRAINT `ck_model_context_run_heads_4` CHECK (working_revision >= base_revision)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_model_context_surface_nodes` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `generation` BIGINT NOT NULL,
    `revision` BIGINT NOT NULL,
    `position` BIGINT NOT NULL,
    `event_sequence_no` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    `__unique_0` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') IS NULL OR `generation` IS NULL OR `revision` IS NULL OR `event_sequence_no` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(`generation`), ':', HEX(`revision`), ':', HEX(`event_sequence_no`)),256) END) STORED,
    UNIQUE KEY `__unique_0` (`__unique_0`),
    CONSTRAINT `ck_model_context_surface_nodes_0` CHECK (generation > 0),
    CONSTRAINT `ck_model_context_surface_nodes_1` CHECK (revision > 0),
    CONSTRAINT `ck_model_context_surface_nodes_2` CHECK (position >= 0),
    CONSTRAINT `ck_model_context_surface_nodes_3` CHECK (event_sequence_no > 0)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_outbound_deliveries` (
    `delivery_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `endpoint_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `content_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `state` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `attempt_count` BIGINT NOT NULL DEFAULT (0),
    `retry_safe` BIGINT NOT NULL DEFAULT (0),
    `next_attempt_at_ms` BIGINT NOT NULL DEFAULT (0),
    `lease_token` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `lease_expires_at_ms` BIGINT,
    `expires_at_ms` BIGINT NOT NULL,
    `receipt_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `last_error` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `created_at_ms` BIGINT NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_outbound_message` (`message_id`(64)),
    KEY `idx_chat_outbound_ready` (`state`(64), `next_attempt_at_ms`, `created_at_ms`),
    `__fk_0` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    `__fk_1` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    CONSTRAINT `ck_outbound_deliveries_0` CHECK (state IN ('pending','leased','sending','succeeded','uncertain','failed','expired','cancelled'))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_post_turn_batches` (
    `batch_id` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `state` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `attempt_count` BIGINT NOT NULL DEFAULT (0),
    `next_attempt_at_ms` BIGINT NOT NULL DEFAULT (0),
    `lease_token` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `lease_expires_at_ms` BIGINT,
    `analysis_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `settled_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('[]'),
    `last_error` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_post_turn_batches_ready` (`state`(64), `next_attempt_at_ms`, `lease_expires_at_ms`),
    UNIQUE KEY uq_post_turn_batch_id (batch_id),
    `__fk_0` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    CONSTRAINT `ck_post_turn_batches_0` CHECK (state IN ('pending', 'claimed', 'failed'))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_post_turn_outcomes` (
    `outcome_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `source_turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `persona_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `source_message_ids` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `accepted_at_ms` BIGINT NOT NULL,
    `execution_mode` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `delivery_attempt_no` BIGINT,
    `task_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `task_attempt` BIGINT,
    `batch_id` VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_post_turn_outcomes_source` (`session_id`(64), `source_turn_id`(64)),
    KEY `idx_chat_post_turn_outcomes_ready` (`batch_id`(64), `accepted_at_ms`, `outcome_id`(64)),
    `__fk_1` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    `__fk_2` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_read_revisions` (
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `scope` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `epoch` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (REPLACE(UUID(),'-','')),
    `revision` BIGINT NOT NULL DEFAULT (0),
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_run_consumed_events` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `revision` BIGINT NOT NULL DEFAULT (0),
    `message_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `recorded_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_crce_run` (`session_id`(64), `run_id`(64), `revision`),
    KEY `idx_crce_message` (`session_id`(64), `message_id`(64))
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_session_creation_requests` (
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `idempotency_key` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    `__unique_1` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN `session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(`session_id`)),256) END) STORED,
    UNIQUE KEY `__unique_1` (`__unique_1`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_sessions` (
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `title` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `title_overridden` BIGINT NOT NULL DEFAULT (0),
    `summary` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `created_at_ms` BIGINT NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `last_message_at_ms` BIGINT,
    `last_user_message_at_ms` BIGINT,
    `last_message_preview` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `last_user_message_preview` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `message_count` BIGINT NOT NULL DEFAULT (0),
    `workspace_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `history_version` BIGINT NOT NULL DEFAULT (0),
    `archived_at_ms` BIGINT,
    `deleted_at_ms` BIGINT,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_sessions_page` (`user_id`(64), `updated_at_ms`, `created_at_ms`, `session_id`(64)),
    `__unique_1` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin GENERATED ALWAYS AS (CASE WHEN `session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(`session_id`)),256) END) STORED,
    UNIQUE KEY `__unique_1` (`__unique_1`),
    KEY `idx_chat_sessions_user_updated` (`user_id`(64), `updated_at_ms`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_task_execution_budgets` (
    `root_turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `max_llm_calls` BIGINT NOT NULL,
    `llm_calls_used` BIGINT NOT NULL DEFAULT (0),
    `max_worker_launches` BIGINT NOT NULL,
    `worker_launches_used` BIGINT NOT NULL DEFAULT (0),
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    `__fk_0` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    CONSTRAINT `ck_task_execution_budgets_0` CHECK (max_llm_calls > 0),
    CONSTRAINT `ck_task_execution_budgets_1` CHECK (llm_calls_used >= 0 AND llm_calls_used <= max_llm_calls),
    CONSTRAINT `ck_task_execution_budgets_2` CHECK (max_worker_launches > 0),
    CONSTRAINT `ck_task_execution_budgets_3` CHECK (
            worker_launches_used >= 0
            AND worker_launches_used <= max_worker_launches
        )
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_turns` (
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `user_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `trace_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `status` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `response_mode` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `execution_mode` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `ux_plan_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('{}'),
    `created_at_ms` BIGINT NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `completed_at_ms` BIGINT,
    `error_text` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `run_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `run_revision` BIGINT NOT NULL DEFAULT (0),
    `run_disposition` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `response_anchor_turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `superseded_by_turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `supersession_reason` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_turns_active_page` (`user_id`(64), `session_id`(64)),
    KEY `idx_chat_turns_user_updated` (`user_id`(64), `updated_at_ms`),
    KEY `idx_chat_turns_session_created` (`session_id`(64), `created_at_ms`)
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_user_turn_delivery` (
    `turn_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `projection_completed` BIGINT NOT NULL DEFAULT (0),
    `delivery_attempt_no` BIGINT NOT NULL DEFAULT (0),
    `delivery_state` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('ready'),
    `current_command_id` BIGINT,
    `runtime_envelope_json` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT ('{}'),
    `request_fingerprint` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL DEFAULT (''),
    `created_at_ms` BIGINT NOT NULL,
    `updated_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    KEY `idx_chat_user_turn_delivery_recovery` (`delivery_state`(64), `updated_at_ms`, `turn_id`(64)),
    CONSTRAINT `ck_user_turn_delivery_0` CHECK (delivery_attempt_no >= 0),
    CONSTRAINT `ck_user_turn_delivery_1` CHECK (delivery_state IN ('ready', 'queued', 'admitted', 'terminal')),
    CONSTRAINT `ck_user_turn_delivery_2` CHECK (
        (delivery_state = 'ready' AND current_command_id IS NULL)
        OR delivery_state = 'terminal'
        OR current_command_id IS NOT NULL
    )
) ENGINE=InnoDB""",
    """CREATE TABLE `chat_workspace_session_cleanup` (
    `workspace_path` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `session_id` LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    `created_at_ms` BIGINT NOT NULL,
    `__pk` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY
) ENGINE=InnoDB""",
    """ALTER TABLE `chat_outbound_deliveries` ADD CONSTRAINT `fk_outbound_deliveries_0` FOREIGN KEY (`__fk_0`) REFERENCES `chat_sessions` (__pk) ON DELETE CASCADE""",
    """ALTER TABLE `chat_outbound_deliveries` ADD CONSTRAINT `fk_outbound_deliveries_1` FOREIGN KEY (`__fk_1`) REFERENCES `chat_messages` (__pk) ON DELETE CASCADE""",
    """ALTER TABLE `chat_post_turn_batches` ADD CONSTRAINT `fk_post_turn_batches_0` FOREIGN KEY (`__fk_0`) REFERENCES `chat_sessions` (__pk) ON DELETE CASCADE""",
    """ALTER TABLE chat_post_turn_outcomes ADD CONSTRAINT fk_post_turn_batch FOREIGN KEY (batch_id) REFERENCES chat_post_turn_batches(batch_id) ON DELETE SET NULL""",
    """ALTER TABLE `chat_post_turn_outcomes` ADD CONSTRAINT `fk_post_turn_outcomes_1` FOREIGN KEY (`__fk_1`) REFERENCES `chat_sessions` (__pk) ON DELETE CASCADE""",
    """ALTER TABLE `chat_post_turn_outcomes` ADD CONSTRAINT `fk_post_turn_outcomes_2` FOREIGN KEY (`__fk_2`) REFERENCES `chat_turns` (__pk) ON DELETE CASCADE""",
    """ALTER TABLE `chat_task_execution_budgets` ADD CONSTRAINT `fk_task_execution_budgets_0` FOREIGN KEY (`__fk_0`) REFERENCES `chat_turns` (__pk) ON DELETE CASCADE""",
    """CREATE TRIGGER `key_chat_assistant_memory_outbox_insert` BEFORE INSERT ON `chat_assistant_memory_outbox` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`canonical_message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_assistant_memory_outbox_update` BEFORE UPDATE ON `chat_assistant_memory_outbox` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`canonical_message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_attachments_insert` BEFORE INSERT ON `chat_attachments` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`attachment_id`)),256); END""",
    """CREATE TRIGGER `key_chat_attachments_update` BEFORE UPDATE ON `chat_attachments` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`attachment_id`)),256); END""",
    """CREATE TRIGGER `key_chat_cleared_message_scopes_insert` BEFORE INSERT ON `chat_cleared_message_scopes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`message_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_cleared_message_scopes_update` BEFORE UPDATE ON `chat_cleared_message_scopes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`message_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_cleared_session_scopes_insert` BEFORE INSERT ON `chat_cleared_session_scopes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_cleared_session_scopes_update` BEFORE UPDATE ON `chat_cleared_session_scopes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_code_delegation_artifacts_insert` BEFORE INSERT ON `chat_code_delegation_artifacts` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`workspace_path`), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`delegation_id`)),256); END""",
    """CREATE TRIGGER `key_chat_code_delegation_artifacts_update` BEFORE UPDATE ON `chat_code_delegation_artifacts` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`workspace_path`), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`delegation_id`)),256); END""",
    """CREATE TRIGGER `key_chat_context_summaries_insert` BEFORE INSERT ON `chat_context_summaries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`summary_id`)),256); END""",
    """CREATE TRIGGER `key_chat_context_summaries_update` BEFORE UPDATE ON `chat_context_summaries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`summary_id`)),256); END""",
    """CREATE TRIGGER `key_chat_context_usage_snapshots_insert` BEFORE INSERT ON `chat_context_usage_snapshots` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_context_usage_snapshots_update` BEFORE UPDATE ON `chat_context_usage_snapshots` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_global_clear_intent_insert` BEFORE INSERT ON `chat_global_clear_intent` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`intent_key`)),256); END""",
    """CREATE TRIGGER `key_chat_global_clear_intent_update` BEFORE UPDATE ON `chat_global_clear_intent` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`intent_key`)),256); END""",
    """CREATE TRIGGER `key_chat_message_asset_refs_insert` BEFORE INSERT ON `chat_message_asset_refs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`), ':', HEX(NEW.`asset_key`)),256); END""",
    """CREATE TRIGGER `key_chat_message_asset_refs_update` BEFORE UPDATE ON `chat_message_asset_refs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`), ':', HEX(NEW.`asset_key`)),256); END""",
    """CREATE TRIGGER `key_chat_message_code_delegation_refs_insert` BEFORE INSERT ON `chat_message_code_delegation_refs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`), ':', HEX(NEW.`delegation_id`)),256); END""",
    """CREATE TRIGGER `key_chat_message_code_delegation_refs_update` BEFORE UPDATE ON `chat_message_code_delegation_refs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`), ':', HEX(NEW.`delegation_id`)),256); END""",
    """CREATE TRIGGER `key_chat_messages_insert` BEFORE INSERT ON `chat_messages` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_messages_update` BEFORE UPDATE ON `chat_messages` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_boundaries_insert` BEFORE INSERT ON `chat_model_context_boundaries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`boundary_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_boundaries_update` BEFORE UPDATE ON `chat_model_context_boundaries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`boundary_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_epochs_insert` BEFORE INSERT ON `chat_model_context_epochs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`epoch_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_epochs_update` BEFORE UPDATE ON `chat_model_context_epochs` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`epoch_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_events_insert` BEFORE INSERT ON `chat_model_context_events` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`event_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_events_update` BEFORE UPDATE ON `chat_model_context_events` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`event_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_heads_insert` BEFORE INSERT ON `chat_model_context_heads` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_model_context_heads_update` BEFORE UPDATE ON `chat_model_context_heads` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_model_context_revisions_insert` BEFORE INSERT ON `chat_model_context_revisions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`generation`), ':', HEX(NEW.`revision`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_revisions_update` BEFORE UPDATE ON `chat_model_context_revisions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`generation`), ':', HEX(NEW.`revision`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_run_heads_insert` BEFORE INSERT ON `chat_model_context_run_heads` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`run_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_run_heads_update` BEFORE UPDATE ON `chat_model_context_run_heads` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`run_id`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_surface_nodes_insert` BEFORE INSERT ON `chat_model_context_surface_nodes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`generation`), ':', HEX(NEW.`revision`), ':', HEX(NEW.`position`)),256); END""",
    """CREATE TRIGGER `key_chat_model_context_surface_nodes_update` BEFORE UPDATE ON `chat_model_context_surface_nodes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')), ':', HEX(NEW.`generation`), ':', HEX(NEW.`revision`), ':', HEX(NEW.`position`)),256); END""",
    """CREATE TRIGGER `key_chat_outbound_deliveries_insert` BEFORE INSERT ON `chat_outbound_deliveries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`delivery_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; SET NEW.`__fk_1` = CASE WHEN NEW.`message_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`message_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_outbound_deliveries_update` BEFORE UPDATE ON `chat_outbound_deliveries` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`delivery_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; SET NEW.`__fk_1` = CASE WHEN NEW.`message_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`message_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_post_turn_batches_insert` BEFORE INSERT ON `chat_post_turn_batches` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`batch_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_post_turn_batches_update` BEFORE UPDATE ON `chat_post_turn_batches` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`batch_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_post_turn_outcomes_insert` BEFORE INSERT ON `chat_post_turn_outcomes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`outcome_id`)),256); SET NEW.`__fk_1` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; SET NEW.`__fk_2` = CASE WHEN NEW.`source_turn_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`source_turn_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_post_turn_outcomes_update` BEFORE UPDATE ON `chat_post_turn_outcomes` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`outcome_id`)),256); SET NEW.`__fk_1` = CASE WHEN NEW.`session_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`session_id`)),256) END; SET NEW.`__fk_2` = CASE WHEN NEW.`source_turn_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`source_turn_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_read_revisions_insert` BEFORE INSERT ON `chat_read_revisions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`user_id`), ':', HEX(NEW.`scope`)),256); END""",
    """CREATE TRIGGER `key_chat_read_revisions_update` BEFORE UPDATE ON `chat_read_revisions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`user_id`), ':', HEX(NEW.`scope`)),256); END""",
    """CREATE TRIGGER `key_chat_run_consumed_events_insert` BEFORE INSERT ON `chat_run_consumed_events` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`session_id`), ':', HEX(NEW.`run_id`), ':', HEX(NEW.`revision`), ':', HEX(NEW.`message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_run_consumed_events_update` BEFORE UPDATE ON `chat_run_consumed_events` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`session_id`), ':', HEX(NEW.`run_id`), ':', HEX(NEW.`revision`), ':', HEX(NEW.`message_id`)),256); END""",
    """CREATE TRIGGER `key_chat_session_creation_requests_insert` BEFORE INSERT ON `chat_session_creation_requests` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`user_id`), ':', HEX(NEW.`idempotency_key`)),256); END""",
    """CREATE TRIGGER `key_chat_session_creation_requests_update` BEFORE UPDATE ON `chat_session_creation_requests` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`user_id`), ':', HEX(NEW.`idempotency_key`)),256); END""",
    """CREATE TRIGGER `key_chat_sessions_insert` BEFORE INSERT ON `chat_sessions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`session_id`)),256); END""",
    """CREATE TRIGGER `key_chat_sessions_update` BEFORE UPDATE ON `chat_sessions` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`session_id`)),256); END""",
    """CREATE TRIGGER `key_chat_task_execution_budgets_insert` BEFORE INSERT ON `chat_task_execution_budgets` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`root_turn_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`root_turn_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`root_turn_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_task_execution_budgets_update` BEFORE UPDATE ON `chat_task_execution_budgets` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`root_turn_id`)),256); SET NEW.`__fk_0` = CASE WHEN NEW.`root_turn_id` IS NULL THEN NULL ELSE SHA2(CONCAT(HEX(NEW.`root_turn_id`)),256) END; END""",
    """CREATE TRIGGER `key_chat_turns_insert` BEFORE INSERT ON `chat_turns` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_turns_update` BEFORE UPDATE ON `chat_turns` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_user_turn_delivery_insert` BEFORE INSERT ON `chat_user_turn_delivery` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_user_turn_delivery_update` BEFORE UPDATE ON `chat_user_turn_delivery` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`turn_id`)),256); END""",
    """CREATE TRIGGER `key_chat_workspace_session_cleanup_insert` BEFORE INSERT ON `chat_workspace_session_cleanup` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`workspace_path`), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `key_chat_workspace_session_cleanup_update` BEFORE UPDATE ON `chat_workspace_session_cleanup` FOR EACH ROW BEGIN SET NEW.__pk = SHA2(CONCAT(HEX(NEW.`workspace_path`), ':', HEX(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.`session_id`, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))),256); END""",
    """CREATE TRIGGER `trg_chat_assistant_memory_outbox_reject_unavailable_session` BEFORE INSERT ON `chat_assistant_memory_outbox` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_attachments_reject_unavailable_session` BEFORE INSERT ON `chat_attachments` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_context_summaries_reject_unavailable_session` BEFORE INSERT ON `chat_context_summaries` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_context_usage_snapshots_read_revision_delete` AFTER DELETE ON `chat_context_usage_snapshots` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_context_usage_snapshots_read_revision_insert` AFTER INSERT ON `chat_context_usage_snapshots` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_context_usage_snapshots_read_revision_update` AFTER UPDATE ON `chat_context_usage_snapshots` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_messages_read_revision_delete` AFTER DELETE ON `chat_messages` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_messages_read_revision_insert` AFTER INSERT ON `chat_messages` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_messages_read_revision_update` AFTER UPDATE ON `chat_messages` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_messages_reject_cleared_message` BEFORE INSERT ON `chat_messages` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_cleared_message_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.message_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.message_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat message was cleared';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_messages_reject_unavailable_session` BEFORE INSERT ON `chat_messages` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_boundaries_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_boundaries` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_epochs_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_epochs` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_events_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_events` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_heads_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_heads` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_revisions_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_revisions` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1 FROM chat_global_clear_intent WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1 FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_run_heads_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_run_heads` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_model_context_surface_nodes_reject_unavailable_session` BEFORE INSERT ON `chat_model_context_surface_nodes` FOR EACH ROW BEGIN
IF NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_outbound_hide` AFTER UPDATE ON `chat_messages` FOR EACH ROW BEGIN
IF NEW.is_visible=0 OR NOT (NEW.content_text <=> OLD.content_text) THEN
UPDATE chat_outbound_deliveries SET
        state=CASE WHEN state='sending' THEN 'uncertain'
                   WHEN state IN ('pending','leased') THEN 'cancelled' ELSE state END,
        content_json='{}',lease_token=NULL,lease_expires_at_ms=NULL
        WHERE message_id=OLD.message_id;
END IF;
END""",
    """CREATE TRIGGER `trg_chat_post_turn_delete_message` AFTER DELETE ON `chat_messages` FOR EACH ROW BEGIN
DELETE FROM chat_post_turn_outcomes WHERE session_id=OLD.session_id AND (
        source_turn_id=OLD.turn_id AND OLD.role='user'
        OR EXISTS (SELECT 1 FROM JSON_TABLE(source_message_ids, '$[*]' COLUMNS(value LONGTEXT PATH '$')) AS json_values WHERE value=OLD.message_id)
    );
END""",
    """CREATE TRIGGER `trg_chat_post_turn_hide_message` AFTER UPDATE ON `chat_messages` FOR EACH ROW BEGIN
IF NEW.is_visible=0 OR NOT (NEW.content_text <=> OLD.content_text) THEN
DELETE FROM chat_post_turn_outcomes WHERE session_id=OLD.session_id AND (
        source_turn_id=OLD.turn_id AND OLD.role='user'
        OR EXISTS (SELECT 1 FROM JSON_TABLE(source_message_ids, '$[*]' COLUMNS(value LONGTEXT PATH '$')) AS json_values WHERE value=OLD.message_id)
    );
END IF;
END""",
    """CREATE TRIGGER `trg_chat_post_turn_reject_unavailable_session` BEFORE INSERT ON `chat_post_turn_outcomes` FOR EACH ROW BEGIN
IF EXISTS (SELECT 1 FROM chat_global_clear_intent)
 OR EXISTS (SELECT 1 FROM chat_cleared_session_scopes WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z'))
 OR NOT EXISTS (SELECT 1 FROM chat_sessions WHERE session_id=NEW.session_id
                AND deleted_at_ms IS NULL AND archived_at_ms IS NULL) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_post_turn_revoke_batch` AFTER DELETE ON `chat_post_turn_outcomes` FOR EACH ROW BEGIN
IF OLD.batch_id IS NOT NULL THEN
DELETE FROM chat_post_turn_batches WHERE batch_id=OLD.batch_id;
END IF;
END""",
    """CREATE TRIGGER `trg_chat_run_consumed_events_reject_unavailable_session` BEFORE INSERT ON `chat_run_consumed_events` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_sessions_read_revision_delete` AFTER DELETE ON `chat_sessions` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,'',1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_sessions_read_revision_insert` AFTER INSERT ON `chat_sessions` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,'',1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_sessions_read_revision_update` AFTER UPDATE ON `chat_sessions` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,'',1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,'',1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_sessions_reject_cleared_session` BEFORE INSERT ON `chat_sessions` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session was cleared';
END IF;
END""",
    """CREATE TRIGGER `trg_chat_turns_read_revision_delete` AFTER DELETE ON `chat_turns` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_turns_read_revision_insert` AFTER INSERT ON `chat_turns` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_turns_read_revision_update` AFTER UPDATE ON `chat_turns` FOR EACH ROW BEGIN INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (OLD.user_id,OLD.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; INSERT INTO chat_read_revisions(user_id,scope,revision) VALUES (NEW.user_id,NEW.session_id,1) ON DUPLICATE KEY UPDATE revision=revision+1; END""",
    """CREATE TRIGGER `trg_chat_turns_reject_unavailable_session` BEFORE INSERT ON `chat_turns` FOR EACH ROW BEGIN
IF EXISTS (
    SELECT 1
    FROM chat_global_clear_intent
    WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1
    FROM chat_cleared_session_scopes AS cleared
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(cleared.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
)
OR EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(sessions.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z') = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(NEW.session_id, 'A', 'a'), 'B', 'b'), 'C', 'c'), 'D', 'd'), 'E', 'e'), 'F', 'f'), 'G', 'g'), 'H', 'h'), 'I', 'i'), 'J', 'j'), 'K', 'k'), 'L', 'l'), 'M', 'm'), 'N', 'n'), 'O', 'o'), 'P', 'p'), 'Q', 'q'), 'R', 'r'), 'S', 's'), 'T', 't'), 'U', 'u'), 'V', 'v'), 'W', 'w'), 'X', 'x'), 'Y', 'y'), 'Z', 'z')
      AND (
          sessions.session_id != NEW.session_id
          OR
          sessions.deleted_at_ms IS NOT NULL
          OR sessions.archived_at_ms IS NOT NULL
      )
) THEN
SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='chat session is unavailable';
END IF;
END""",
 ]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.get_bind().exec_driver_sql(statement)


def downgrade() -> None:
    raise RuntimeError("Chat storage migrations are forward-only")
