use axum::extract::{Path, Query};
use axum::http::StatusCode;
use axum::Json;
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::Path as FsPath;
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

use crate::db;

use super::query::{append_like_search, clamp_limit, clamp_offset, PaginationQuery, DEFAULT_LIMIT};
use super::{l2_projection_backlog_json, read_l2_projection_backlog};

// ---------------------------------------------------------------------------
// L2 cognition statistics
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/statistics — L2 pipeline statistics.
pub async fn get_l2_statistics() -> Json<Value> {
    let result = tokio::task::spawn_blocking(build_l2_statistics)
        .await
        .unwrap_or_else(|_| json!({}));
    Json(result)
}

fn build_l2_statistics() -> Value {
    let conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => {
            return json!({
                "is_running": false,
                "relation_count": 0,
                "assertion_count": 0,
                "projection_backlog": {"pending": 0, "claimed": 0, "completed": 0, "failed": 0},
            })
        }
    };

    let rel_count = db::count_rows(
        &conn,
        "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'",
        &[],
    );
    let tom_count = db::count_rows(&conn, "SELECT COUNT(*) FROM tom_trait_assertions", &[]);

    let backlog = read_l2_projection_backlog(&conn);

    json!({
        "is_running": backlog.running > 0,
        "relation_count": rel_count,
        "assertion_count": tom_count,
        "extract_enqueued": 0,
        "extract_completed": 0,
        "extract_failed": 0,
        "extract_skipped": 0,
        "reconcile_enqueued": 0,
        "reconcile_completed": 0,
        "reconcile_failed": 0,
        "snapshot_enqueued": 0,
        "snapshot_completed": 0,
        "snapshot_failed": 0,
        "relations_written": 0,
        "assertions_written": 0,
        "extract_by_evidence_class": {},
        "skip_by_reason": {},
        "projection_backlog": l2_projection_backlog_json(backlog),
    })
}
// ---------------------------------------------------------------------------
// L2 Relations
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/relations — active knowledge graph triples.
pub async fn list_l2_relations(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let search_query = params.query.clone();
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let mut where_parts = vec!["status = 'active'".to_string()];
                    let mut bind: Vec<rusqlite::types::Value> = Vec::new();
                    append_like_search(
                        &mut where_parts,
                        &mut bind,
                        &[
                            "triple_id",
                            "subject_id",
                            "subject_type",
                            "predicate",
                            "object_id",
                            "object_type",
                            "fact_kind",
                            "evidence_event_ids",
                            "evidence_text",
                            "natural_summary",
                            "source_type",
                            "extraction_method",
                            "evidence_class",
                            "status",
                        ],
                        search_query.as_deref(),
                    );
                    let where_clause = format!("WHERE {}", where_parts.join(" AND "));
                    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let total = db::count_rows(
                        &conn,
                        &format!("SELECT COUNT(*) FROM knowledge_graph {where_clause}"),
                        &count_refs,
                    );
                    bind.push(rusqlite::types::Value::Integer(limit));
                    bind.push(rusqlite::types::Value::Integer(offset));
                    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let items = db::query_to_json_array(
                        &conn,
                        &format!(
                            "SELECT * FROM knowledge_graph \
                             {where_clause} \
                             ORDER BY updated_at DESC LIMIT ? OFFSET ?"
                        ),
                        &refs,
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Assertions
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/assertions — ToM trait assertions.
pub async fn list_l2_assertions(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let search_query = params.query.clone();
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let mut where_parts: Vec<String> = Vec::new();
                    let mut bind: Vec<rusqlite::types::Value> = Vec::new();
                    append_like_search(
                        &mut where_parts,
                        &mut bind,
                        &[
                            "assertion_id",
                            "entity_id",
                            "entity_type",
                            "trait_family",
                            "trait_name",
                            "trait_value",
                            "evidence_events",
                            "source_domain",
                            "inference_depth",
                            "validation_state",
                            "target_entity_id",
                            "target_entity_type",
                            "target_scope",
                            "temporal_scope",
                            "context_ref_id",
                            "status",
                            "superseded_by",
                            "memory_subdomain",
                            "natural_summary",
                        ],
                        search_query.as_deref(),
                    );
                    let where_clause = sql_where_clause(&where_parts);
                    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let total = db::count_rows(
                        &conn,
                        &format!("SELECT COUNT(*) FROM tom_trait_assertions {where_clause}"),
                        &count_refs,
                    );
                    bind.push(rusqlite::types::Value::Integer(limit));
                    bind.push(rusqlite::types::Value::Integer(offset));
                    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let items = db::query_to_json_array(
                        &conn,
                        &format!(
                            "SELECT * FROM tom_trait_assertions \
                             {where_clause} \
                             ORDER BY updated_at DESC LIMIT ? OFFSET ?"
                        ),
                        &refs,
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

#[derive(Deserialize)]
pub struct AssertionFeedbackBody {
    feedback: String,
}

#[derive(Deserialize)]
pub struct AssertionCorrectionBody {
    new_value: String,
    #[allow(dead_code)]
    reason: Option<String>,
}

#[derive(Debug)]
enum AssertionWriteError {
    InvalidRequest,
    NotFound,
    StoreUnavailable,
    WriteFailed,
}

impl AssertionWriteError {
    fn response(self) -> (StatusCode, Json<Value>) {
        match self {
            AssertionWriteError::InvalidRequest => (
                StatusCode::BAD_REQUEST,
                Json(json!({"detail": "Invalid assertion feedback request"})),
            ),
            AssertionWriteError::NotFound => (
                StatusCode::NOT_FOUND,
                Json(json!({"detail": "Assertion not found"})),
            ),
            AssertionWriteError::StoreUnavailable => (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(json!({"detail": "Memory store unavailable"})),
            ),
            AssertionWriteError::WriteFailed => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"detail": "Failed to save assertion change"})),
            ),
        }
    }
}

/// PATCH /api/memory/l2/assertions/{assertion_id}/feedback — apply user feedback.
pub async fn submit_l2_assertion_feedback(
    Path(assertion_id): Path<String>,
    Json(body): Json<AssertionFeedbackBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || {
        apply_l2_assertion_feedback(&assertion_id, &body.feedback)
    })
    .await
    .unwrap_or(Err(AssertionWriteError::WriteFailed));

    match result {
        Ok(value) => (StatusCode::OK, Json(value)),
        Err(error) => error.response(),
    }
}

/// POST /api/memory/l2/assertions/{assertion_id}/correct — save a user correction.
pub async fn correct_l2_assertion(
    Path(assertion_id): Path<String>,
    Json(body): Json<AssertionCorrectionBody>,
) -> (StatusCode, Json<Value>) {
    let result = tokio::task::spawn_blocking(move || {
        correct_l2_assertion_value(&assertion_id, &body.new_value)
    })
    .await
    .unwrap_or(Err(AssertionWriteError::WriteFailed));

    match result {
        Ok(value) => (StatusCode::OK, Json(value)),
        Err(error) => error.response(),
    }
}

fn apply_l2_assertion_feedback(
    assertion_id: &str,
    feedback: &str,
) -> Result<Value, AssertionWriteError> {
    apply_l2_assertion_feedback_at_path(&db::memory_db_path(), assertion_id, feedback)
}

fn apply_l2_assertion_feedback_at_path(
    db_path: &FsPath,
    assertion_id: &str,
    feedback: &str,
) -> Result<Value, AssertionWriteError> {
    let feedback = feedback.trim();
    if !matches!(feedback, "confirmed" | "rejected") {
        return Err(AssertionWriteError::InvalidRequest);
    }

    let conn = db::open_readwrite(db_path).ok_or(AssertionWriteError::StoreUnavailable)?;
    let existing = load_l2_assertion(&conn, assertion_id)?.ok_or(AssertionWriteError::NotFound)?;
    let current_confidence = json_f64(&existing, "confidence_score", 0.0);
    let current_state = json_string(&existing, "validation_state", "tentative");
    let now = now_seconds();
    let (new_confidence, new_state) = if feedback == "confirmed" {
        (
            (current_confidence + 0.20).min(0.95),
            if current_state == "contradicted" {
                current_state
            } else {
                "stable".to_string()
            },
        )
    } else {
        (0.10, "user_rejected".to_string())
    };

    conn.execute(
        "UPDATE tom_trait_assertions
         SET user_feedback = ?1, user_feedback_at = ?2,
             confidence_score = ?3, validation_state = ?4, status = ?5, updated_at = ?6
         WHERE assertion_id = ?7",
        rusqlite::params![
            feedback,
            now,
            new_confidence,
            new_state,
            new_state,
            now,
            assertion_id
        ],
    )
    .map_err(|_| AssertionWriteError::WriteFailed)?;

    load_l2_assertion(&conn, assertion_id)?.ok_or(AssertionWriteError::NotFound)
}

fn correct_l2_assertion_value(
    assertion_id: &str,
    new_value: &str,
) -> Result<Value, AssertionWriteError> {
    correct_l2_assertion_value_at_path(&db::memory_db_path(), assertion_id, new_value)
}

fn correct_l2_assertion_value_at_path(
    db_path: &FsPath,
    assertion_id: &str,
    new_value: &str,
) -> Result<Value, AssertionWriteError> {
    let new_value = new_value.trim();
    if new_value.is_empty() {
        return Err(AssertionWriteError::InvalidRequest);
    }

    let mut conn = db::open_readwrite(db_path).ok_or(AssertionWriteError::StoreUnavailable)?;
    let existing = load_l2_assertion(&conn, assertion_id)?.ok_or(AssertionWriteError::NotFound)?;
    let now = now_seconds();
    let new_assertion_id = format!("assert_{}", Uuid::new_v4().simple());
    let evidence_events = json_storage_text(&existing, "evidence_events", "[]");

    let tx = conn
        .transaction()
        .map_err(|_| AssertionWriteError::WriteFailed)?;
    tx.execute(
        "UPDATE tom_trait_assertions
         SET status = 'superseded', superseded_by = ?1, superseded_at = ?2, updated_at = ?3
         WHERE assertion_id = ?4",
        rusqlite::params![new_assertion_id, now, now, assertion_id],
    )
    .map_err(|_| AssertionWriteError::WriteFailed)?;
    tx.execute(
        "INSERT INTO tom_trait_assertions(
            assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
            confidence_score, evidence_events, volatility_index, source_domain,
            inference_depth, validation_state, first_inferred_at, last_validated_at,
            target_entity_id, target_entity_type, target_scope, temporal_scope,
            decay_policy, decay_anchor_at, context_ref_id, expires_at,
            status, privacy_scope, user_feedback, user_feedback_at,
            created_at, updated_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14,
                   ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22, ?23, ?24, ?25, ?26, ?27, ?28)",
        rusqlite::params![
            new_assertion_id,
            json_string(&existing, "entity_id", ""),
            json_string(&existing, "entity_type", ""),
            json_string(&existing, "trait_family", ""),
            json_string(&existing, "trait_name", ""),
            new_value,
            0.95_f64,
            evidence_events,
            json_f64(&existing, "volatility_index", 0.0),
            "user_correction",
            "explicit",
            "stable",
            json_f64(&existing, "first_inferred_at", now),
            now,
            json_string(&existing, "target_entity_id", ""),
            json_string(&existing, "target_entity_type", ""),
            json_string(&existing, "target_scope", "global"),
            json_string(&existing, "temporal_scope", "session"),
            json_nullable_string(&existing, "decay_policy"),
            json_nullable_f64(&existing, "decay_anchor_at"),
            json_string(&existing, "context_ref_id", ""),
            json_nullable_f64(&existing, "expires_at"),
            "stable",
            json_string(&existing, "privacy_scope", "private"),
            "confirmed",
            now,
            now,
            now,
        ],
    )
    .map_err(|_| AssertionWriteError::WriteFailed)?;
    tx.commit().map_err(|_| AssertionWriteError::WriteFailed)?;

    load_l2_assertion(&conn, &new_assertion_id)?.ok_or(AssertionWriteError::NotFound)
}

fn load_l2_assertion(
    conn: &rusqlite::Connection,
    assertion_id: &str,
) -> Result<Option<Value>, AssertionWriteError> {
    let rows = db::query_to_json_array(
        conn,
        "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?1",
        &[&assertion_id],
    );
    Ok(rows.into_iter().next())
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0)
}

fn json_string(value: &Value, key: &str, default: &str) -> String {
    match value.get(key) {
        Some(Value::String(text)) if !text.is_empty() => text.clone(),
        Some(Value::Number(number)) => number.to_string(),
        Some(Value::Bool(flag)) => flag.to_string(),
        _ => default.to_string(),
    }
}

fn json_storage_text(value: &Value, key: &str, default: &str) -> String {
    match value.get(key) {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Array(_)) | Some(Value::Object(_)) => value[key].to_string(),
        _ => default.to_string(),
    }
}

fn json_f64(value: &Value, key: &str, default: f64) -> f64 {
    value.get(key).and_then(Value::as_f64).unwrap_or(default)
}

fn json_nullable_f64(value: &Value, key: &str) -> Option<f64> {
    value.get(key).and_then(Value::as_f64)
}

fn json_nullable_string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
        .map(ToOwned::to_owned)
}

#[cfg(test)]
mod assertion_write_tests {
    use super::*;

    fn seeded_memory_db() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "magi-gateway-l2-assertions-{}.db",
            Uuid::new_v4().simple()
        ));
        let _ = std::fs::remove_file(&path);
        let conn = rusqlite::Connection::open(&path).unwrap();
        conn.execute_batch(
            r#"
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
                natural_summary TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain,
                inference_depth, validation_state, first_inferred_at, last_validated_at,
                target_entity_id, target_entity_type, target_scope, temporal_scope,
                status, privacy_scope, created_at, updated_at
            ) VALUES (
                'assert-1', 'user:self', 'user', 'preference', 'preference.music', 'jazz',
                0.55, '["evt-1"]', 0.2, 'chat', 'explicit', 'tentative', 1000.0, 1000.0,
                '', '', 'global', 'session', 'active', 'private', 1000.0, 1000.0
            );
            "#,
        )
        .unwrap();
        path
    }

    #[test]
    fn feedback_confirmation_updates_assertion_state() {
        let path = seeded_memory_db();

        let updated = apply_l2_assertion_feedback_at_path(&path, "assert-1", "confirmed").unwrap();

        assert_eq!(updated["assertion_id"], "assert-1");
        assert_eq!(updated["user_feedback"], "confirmed");
        assert_eq!(updated["validation_state"], "stable");
        assert_eq!(updated["status"], "stable");
        assert_eq!(updated["confidence_score"].as_f64().unwrap(), 0.75);

        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn correction_supersedes_old_assertion_and_returns_replacement() {
        let path = seeded_memory_db();

        let replacement = correct_l2_assertion_value_at_path(&path, "assert-1", "blues").unwrap();

        assert_eq!(replacement["trait_value"], "blues");
        assert_eq!(replacement["source_domain"], "user_correction");
        assert_eq!(replacement["inference_depth"], "explicit");
        assert_eq!(replacement["validation_state"], "stable");
        assert_eq!(replacement["user_feedback"], "confirmed");
        assert_eq!(replacement["confidence_score"].as_f64().unwrap(), 0.95);

        let conn = rusqlite::Connection::open(&path).unwrap();
        let old = load_l2_assertion(&conn, "assert-1").unwrap().unwrap();
        assert_eq!(old["status"], "superseded");
        assert_eq!(old["superseded_by"], replacement["assertion_id"]);

        let _ = std::fs::remove_file(path);
    }
}

#[cfg(test)]
mod l2_statistics_tests {
    use super::build_l2_statistics;
    use crate::db;
    use rusqlite::Connection;
    use std::path::PathBuf;
    use std::sync::MutexGuard;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct IsolatedMagiBase {
        previous_base_dir: Option<PathBuf>,
        root: PathBuf,
        _lock: MutexGuard<'static, ()>,
    }

    impl Drop for IsolatedMagiBase {
        fn drop(&mut self) {
            db::set_magi_base_dir_override_for_tests(self.previous_base_dir.take());
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    fn isolated_magi_base(label: &str) -> IsolatedMagiBase {
        let lock = db::magi_base_dir_override_test_lock();
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "magi-gateway-l2-{label}-{}-{nonce}",
            std::process::id()
        ));
        let magi_base = root.join(".magi");
        std::fs::create_dir_all(magi_base.join("data").join("memory")).expect("create memory dir");
        let previous_base_dir = db::set_magi_base_dir_override_for_tests(Some(magi_base));
        IsolatedMagiBase {
            previous_base_dir,
            root,
            _lock: lock,
        }
    }

    fn seed_memory_db(statuses: &[&str]) {
        let conn = Connection::open(db::memory_db_path()).expect("open memory db");
        conn.execute_batch(
            "CREATE TABLE l2_projection_jobs(status TEXT NOT NULL);
             CREATE TABLE knowledge_graph(status TEXT, updated_at REAL);
             CREATE TABLE tom_trait_assertions(assertion_id TEXT);",
        )
        .expect("create memory tables");
        for status in statuses {
            conn.execute(
                "INSERT INTO l2_projection_jobs(status) VALUES (?1)",
                [status],
            )
            .expect("insert projection job");
        }
    }

    #[test]
    fn reports_queued_and_running_projection_backlog() {
        let _base = isolated_magi_base("queued-running-backlog");
        seed_memory_db(&[
            "pending", "queued", "queued", "running", "running", "running",
        ]);

        let stats = build_l2_statistics();

        assert_eq!(stats["is_running"], true);
        assert_eq!(stats["projection_backlog"]["pending"], 1);
        assert_eq!(stats["projection_backlog"]["queued"], 2);
        assert_eq!(stats["projection_backlog"]["running"], 3);
        assert_eq!(stats["projection_backlog"]["claimed"], 5);
    }
}

// ---------------------------------------------------------------------------
// L2 Entities (with aliases join)
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/entities — entity catalog with aliases.
pub async fn list_l2_entities(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let search_query = params.query.clone();
    let result =
        tokio::task::spawn_blocking(move || build_l2_entities(limit, offset, search_query))
            .await
            .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset}));
    Json(result)
}

fn build_l2_entities(limit: i64, offset: i64, query: Option<String>) -> Value {
    let conn = match db::open_readonly(&db::memory_db_path()) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": limit, "offset": offset}),
    };

    let mut where_parts: Vec<String> = Vec::new();
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();
    append_like_search(
        &mut where_parts,
        &mut bind,
        &[
            "ec.entity_id",
            "ec.canonical_name",
            "ec.entity_type",
            "(SELECT GROUP_CONCAT(ea.alias_text, ' ') FROM entity_aliases ea WHERE ea.entity_id = ec.entity_id)",
            "(SELECT GROUP_CONCAT(ea.normalized_alias, ' ') FROM entity_aliases ea WHERE ea.entity_id = ec.entity_id)",
        ],
        query.as_deref(),
    );
    let where_clause = sql_where_clause(&where_parts);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let total = db::count_rows(
        &conn,
        &format!("SELECT COUNT(*) FROM entity_catalog AS ec {where_clause}"),
        &count_refs,
    );

    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let entities = db::query_to_json_array(
        &conn,
        &format!(
            "SELECT ec.entity_id, ec.canonical_name, ec.entity_type, ec.embedding_status, ec.last_embedded_at \
             FROM entity_catalog AS ec {where_clause} ORDER BY ec.entity_id ASC LIMIT ? OFFSET ?"
        ),
        &refs,
    );

    // Collect entity_ids from the current page to scope the alias query.
    let entity_ids: Vec<String> = entities
        .iter()
        .filter_map(|e| {
            e.get("entity_id")
                .and_then(|v| v.as_str())
                .map(String::from)
        })
        .collect();

    let mut alias_map: HashMap<String, Vec<String>> = HashMap::new();
    if !entity_ids.is_empty() {
        let placeholders: String = entity_ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let alias_sql = format!(
            "SELECT entity_id, alias_text FROM entity_aliases \
             WHERE entity_id IN ({}) ORDER BY normalized_alias ASC",
            placeholders
        );
        let bind_values: Vec<rusqlite::types::Value> = entity_ids
            .iter()
            .map(|id| rusqlite::types::Value::Text(id.clone()))
            .collect();
        let refs: Vec<&dyn rusqlite::types::ToSql> = bind_values
            .iter()
            .map(|v| v as &dyn rusqlite::types::ToSql)
            .collect();
        let alias_rows = db::query_to_json_array(&conn, &alias_sql, &refs);
        for row in &alias_rows {
            if let (Some(eid), Some(text)) = (
                row.get("entity_id").and_then(|v| v.as_str()),
                row.get("alias_text").and_then(|v| v.as_str()),
            ) {
                alias_map
                    .entry(eid.to_string())
                    .or_default()
                    .push(text.to_string());
            }
        }
    }

    let items: Vec<Value> = entities
        .into_iter()
        .map(|mut e| {
            if let Some(obj) = e.as_object_mut() {
                let eid = obj.get("entity_id").and_then(|v| v.as_str()).unwrap_or("");
                let aliases = alias_map.remove(eid).unwrap_or_default();
                obj.insert("aliases".to_string(), json!(aliases));
            }
            e
        })
        .collect();

    json!({"items": items, "total": total, "limit": limit, "offset": offset})
}

// ---------------------------------------------------------------------------
// L2 Mentions
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/mentions — entity mentions.
pub async fn list_l2_mentions(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let total = db::count_rows(&conn, "SELECT COUNT(*) FROM entity_mentions", &[]);
                    let items = db::query_to_json_array(
                        &conn,
                        "SELECT * FROM entity_mentions \
                         ORDER BY mention_id DESC LIMIT ?1 OFFSET ?2",
                        rusqlite::params![limit, offset],
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

// ---------------------------------------------------------------------------
// L2 Snapshots
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/snapshots — ToM entity snapshots.
pub async fn list_l2_snapshots(Query(params): Query<PaginationQuery>) -> Json<Value> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let search_query = params.query.clone();
    Json(
        tokio::task::spawn_blocking(move || {
            let empty = json!({"items": [], "total": 0, "limit": limit, "offset": offset});
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    let mut where_parts: Vec<String> = Vec::new();
                    let mut bind: Vec<rusqlite::types::Value> = Vec::new();
                    append_like_search(
                        &mut where_parts,
                        &mut bind,
                        &[
                            "snapshot_id",
                            "entity_id",
                            "entity_type",
                            "core_traits",
                            "sensitive_triggers",
                            "preferences",
                            "public_sentiment_profile",
                            "relationship_topology",
                            "current_context",
                            "current_mood",
                            "update_source_assertion_ids",
                            "core_traits_history",
                            "preferences_history",
                            "relationship_history",
                            "active_record_ids",
                            "superseded_record_ids",
                            "emerging_signals",
                            "mood_trajectory",
                        ],
                        search_query.as_deref(),
                    );
                    let where_clause = sql_where_clause(&where_parts);
                    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let total = db::count_rows(
                        &conn,
                        &format!("SELECT COUNT(*) FROM tom_snapshots {where_clause}"),
                        &count_refs,
                    );
                    // Only select columns the frontend uses; skip heavy
                    // history/evolution columns (relationship_history etc.).
                    bind.push(rusqlite::types::Value::Integer(limit));
                    bind.push(rusqlite::types::Value::Integer(offset));
                    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
                        .iter()
                        .map(|v| v as &dyn rusqlite::types::ToSql)
                        .collect();
                    let items = db::query_to_json_array(
                        &conn,
                        &format!(
                            "SELECT snapshot_id, entity_id, entity_type, \
                         core_traits, preferences, relationship_topology, \
                         current_stress_level, current_mood, current_engagement, \
                         current_context, interaction_count, last_interaction_at, \
                         last_updated_at, snapshot_version, created_at, \
                         sensitive_triggers, public_sentiment_profile, \
                         update_source_assertion_ids \
                         FROM tom_snapshots \
                         {where_clause} \
                         ORDER BY last_updated_at DESC LIMIT ? OFFSET ?"
                        ),
                        &refs,
                    );
                    json!({"items": items, "total": total, "limit": limit, "offset": offset})
                })
                .unwrap_or(empty)
        })
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": limit, "offset": offset})),
    )
}

fn sql_where_clause(where_parts: &[String]) -> String {
    if where_parts.is_empty() {
        String::new()
    } else {
        format!("WHERE {} ", where_parts.join(" AND "))
    }
}

// ---------------------------------------------------------------------------
// L2 Conflict Rules
// ---------------------------------------------------------------------------

/// GET /api/memory/l2/conflict-rules — graph conflict resolution rules.
pub async fn list_l2_conflict_rules() -> Json<Value> {
    Json(
        tokio::task::spawn_blocking(move || {
            db::open_readonly(&db::memory_db_path())
                .map(|conn| {
                    json!(db::query_to_json_array(
                        &conn,
                        "SELECT * FROM graph_conflict_rules ORDER BY predicate ASC",
                        rusqlite::params![],
                    ))
                })
                .unwrap_or_else(|| json!([]))
        })
        .await
        .unwrap_or_else(|_| json!([])),
    )
}

// ---------------------------------------------------------------------------
// ToM Snapshot (single entity)
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct TomQuery {
    pub entity_type: Option<String>,
}

/// GET /api/memory/tom/{entity_id} — ToM snapshot for an entity.
pub async fn get_tom_snapshot(
    Path(entity_id): Path<String>,
    Query(params): Query<TomQuery>,
) -> Result<Json<Value>, StatusCode> {
    let result = tokio::task::spawn_blocking(move || {
        let entity_type = params.entity_type.as_deref().unwrap_or("user");
        let conn = db::open_readonly(&db::memory_db_path())?;
        let rows = db::query_to_json_array(
            &conn,
            "SELECT * FROM tom_snapshots WHERE entity_id = ?1 AND entity_type = ?2",
            rusqlite::params![entity_id, entity_type],
        );
        rows.into_iter().next()
    })
    .await
    .unwrap_or(None);
    match result {
        Some(v) => Ok(Json(v)),
        None => Err(StatusCode::NOT_FOUND),
    }
}
