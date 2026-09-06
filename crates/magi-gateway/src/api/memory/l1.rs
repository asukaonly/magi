use axum::extract::Query;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{clamp_limit, clamp_offset, L1EventsQuery, DEFAULT_LIMIT};

// ---------------------------------------------------------------------------
// L1 Events
// ---------------------------------------------------------------------------

/// GET /api/memory/l1/events — query fact_events from l1_events.db.
pub async fn list_l1_events(Query(params): Query<L1EventsQuery>) -> Response {
    match tokio::task::spawn_blocking(move || build_l1_events_response(&params)).await {
        Ok(Ok(result)) => Json(result).into_response(),
        Ok(Err(error)) => {
            eprintln!("Failed to read L1 event store: {error:?}");
            l1_store_unavailable_response()
        }
        Err(error) => {
            eprintln!("L1 event store read task failed: {error}");
            l1_store_unavailable_response()
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
enum L1EventsReadError {
    StoreUnavailable,
    ReadFailed(String),
}

fn l1_store_unavailable_response() -> Response {
    (
        StatusCode::SERVICE_UNAVAILABLE,
        Json(json!({
            "success": false,
            "message": "The L1 event store is temporarily unavailable",
            "error_code": "memory_l1_store_unavailable",
        })),
    )
        .into_response()
}

fn build_l1_events_response(params: &L1EventsQuery) -> Result<Value, L1EventsReadError> {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let path = db::l1_events_db_path();
    if !path.is_file() {
        return Err(L1EventsReadError::StoreUnavailable);
    }
    let conn = db::open_readonly_result(&path)
        .map_err(|error| L1EventsReadError::ReadFailed(error.to_string()))?;

    let mut where_parts = vec!["fe.deleted_at IS NULL".to_string()];
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();

    if let Some(ref v) = params.event_type {
        where_parts.push("fe.event_type = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.event_id {
        where_parts.push("fe.event_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.user_id {
        where_parts.push("fe.user_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.session_id {
        where_parts.push("fe.session_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source {
        where_parts.push("fe.source = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source_item_id {
        where_parts.push("fe.source_item_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.idempotency_key {
        where_parts.push("fe.idempotency_key = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    bind_date_filter(
        &mut where_parts,
        &mut bind,
        "start",
        params.start_date.as_deref(),
    );
    bind_date_filter(
        &mut where_parts,
        &mut bind,
        "end",
        params.end_date.as_deref(),
    );
    if let Some(ref v) = params.query {
        where_parts.push(
            "fe.event_id IN (SELECT event_id FROM l1_events_fts WHERE content MATCH ?)".into(),
        );
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }

    let where_clause = where_parts.join(" AND ");

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM fact_events fe WHERE {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let total = db::count_rows_result(&conn, &count_sql, &count_refs)
        .map_err(|error| L1EventsReadError::ReadFailed(error.to_string()))?;

    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));

    let sql = format!(
        "SELECT \
            fe.id, \
            fe.event_id, \
            fe.event_id AS correlation_id, \
            fe.timestamp, \
            fe.created_at, \
            fe.event_type, \
            fe.source, \
            fe.source_item_id, \
            fe.idempotency_key, \
            CASE fe.memory_domain \
                WHEN 1 THEN 'user_authored' \
                WHEN 2 THEN 'external_activity' \
                WHEN 3 THEN 'runtime_telemetry' \
                WHEN 4 THEN 'system_control' \
                WHEN 5 THEN 'interaction' \
                ELSE 'user_authored' \
            END AS memory_domain, \
            'l1_only' AS ingest_target, \
            fe.cognition_eligible, \
            'none' AS tom_depth, \
            CASE fe.retention_class \
                WHEN 1 THEN 'disposable' \
                WHEN 2 THEN 'compressible' \
                WHEN 3 THEN 'permanent' \
                ELSE 'compressible' \
            END AS retention_class, \
            fe.session_id, \
            fe.turn_id, \
            fe.user_id, \
            NULL AS task_id, \
            fe.content, \
            CASE fe.author_type \
                WHEN 1 THEN 'user' \
                WHEN 2 THEN 'assistant' \
                WHEN 3 THEN 'tool' \
                WHEN 4 THEN 'system' \
                WHEN 5 THEN 'source' \
                WHEN 6 THEN 'external' \
                ELSE 'unknown' \
            END AS author_type, \
            CASE fe.content_type \
                WHEN 1 THEN 'text' \
                WHEN 2 THEN 'tool_result' \
                WHEN 3 THEN 'observation' \
                ELSE 'unknown' \
            END AS content_type, \
            fe.importance_score, \
            1 AS level, \
            fe.media_path, \
            fe.metadata_json, \
            CASE COALESCE(es.embedding_status, 1) \
                WHEN 1 THEN 'disabled' \
                WHEN 2 THEN 'pending' \
                WHEN 3 THEN 'ready' \
                WHEN 4 THEN 'failed' \
                WHEN 5 THEN 'skipped' \
                ELSE 'disabled' \
            END AS embedding_status, \
            es.embedding_profile_id, \
            es.embedding_chunk_count, \
            es.last_embedded_at, \
            CASE fe.evidence_status \
                WHEN 1 THEN 'unknown' \
                WHEN 2 THEN 'classified' \
                WHEN 3 THEN 'classification_error' \
                WHEN 4 THEN 'policy_error' \
                ELSE 'unknown' \
            END AS evidence_status, \
            CASE fe.evidence_class \
                WHEN 1 THEN 'unknown' \
                WHEN 2 THEN 'user_self_report' \
                WHEN 3 THEN 'assistant_quote' \
                WHEN 4 THEN 'assistant_tool_grounded' \
                WHEN 5 THEN 'assistant_freeform' \
                WHEN 6 THEN 'assistant_runtime_derivation' \
                WHEN 7 THEN 'external_observation' \
                WHEN 8 THEN 'system_runtime' \
                WHEN 9 THEN 'user_question' \
                WHEN 10 THEN 'user_request' \
                ELSE 'unknown' \
            END AS evidence_class, \
            fe.evidence_rule_version, \
            CASE fe.l1_retrieval_scope \
                WHEN 1 THEN 'none' \
                WHEN 2 THEN 'fact_authoritative' \
                WHEN 3 THEN 'conversation_only' \
                WHEN 4 THEN 'audit_only' \
                WHEN 5 THEN 'source_backlink_only' \
                ELSE 'none' \
            END AS l1_retrieval_scope, \
            fe.deleted_at \
            FROM fact_events fe \
            LEFT JOIN l1_event_embedding_state es USING(event_id) \
            WHERE {} ORDER BY fe.timestamp DESC LIMIT ? OFFSET ?",
        where_clause
    );
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();

    let items = db::query_to_json_array_result(&conn, &sql, &refs)
        .map_err(|error| L1EventsReadError::ReadFailed(error.to_string()))?;
    Ok(json!({"items": items, "total": total, "limit": limit, "offset": offset}))
}

fn bind_date_filter(
    where_parts: &mut Vec<String>,
    bind: &mut Vec<rusqlite::types::Value>,
    boundary: &str,
    raw_value: Option<&str>,
) {
    let value = raw_value.unwrap_or("").trim();
    if value.is_empty() {
        return;
    }

    if let Ok(ts) = value.parse::<f64>() {
        match boundary {
            "start" => where_parts.push("timestamp >= ?".into()),
            _ => where_parts.push("timestamp <= ?".into()),
        }
        bind.push(rusqlite::types::Value::Real(ts));
        return;
    }

    if !is_iso_day(value) {
        return;
    }

    match boundary {
        "start" => where_parts.push("date(timestamp, 'unixepoch', 'localtime') >= ?".into()),
        _ => where_parts.push("date(timestamp, 'unixepoch', 'localtime') <= ?".into()),
    }
    bind.push(rusqlite::types::Value::Text(value.to_string()));
}

fn is_iso_day(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 10
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| index == 4 || index == 7 || byte.is_ascii_digit())
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::MutexGuard;

    use super::*;

    static TEST_COUNTER: AtomicU32 = AtomicU32::new(0);

    struct BaseDirGuard {
        previous_base_dir: Option<PathBuf>,
        path: PathBuf,
        _lock: MutexGuard<'static, ()>,
    }

    impl Drop for BaseDirGuard {
        fn drop(&mut self) {
            db::set_magi_base_dir_override_for_tests(self.previous_base_dir.take());
            let _ = std::fs::remove_dir_all(&self.path);
        }
    }

    fn isolated_base_dir(label: &str) -> BaseDirGuard {
        let lock = db::magi_base_dir_override_test_lock();
        let n = TEST_COUNTER.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "magi-gateway-l1-{label}-{}-{n}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).unwrap();
        let previous_base_dir = db::set_magi_base_dir_override_for_tests(Some(path.clone()));
        BaseDirGuard {
            previous_base_dir,
            path,
            _lock: lock,
        }
    }

    fn seed_l1_events_for_date_filter() {
        let path = db::l1_events_db_path();
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let conn = rusqlite::Connection::open(path).unwrap();
        conn.execute_batch(
            r#"
            CREATE TABLE fact_events (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL,
                event_type TEXT,
                source TEXT,
                source_item_id TEXT,
                idempotency_key TEXT,
                memory_domain INTEGER,
                cognition_eligible INTEGER,
                retention_class INTEGER,
                session_id TEXT,
                turn_id TEXT,
                user_id TEXT,
                content TEXT,
                author_type INTEGER,
                content_type INTEGER,
                importance_score REAL,
                media_path TEXT,
                metadata_json TEXT,
                evidence_status INTEGER,
                evidence_class INTEGER,
                evidence_rule_version INTEGER,
                l1_retrieval_scope INTEGER,
                deleted_at REAL
            );

            CREATE TABLE l1_event_embedding_state (
                event_id TEXT PRIMARY KEY,
                embedding_status INTEGER,
                embedding_profile_id TEXT,
                embedding_chunk_count INTEGER,
                last_embedded_at REAL,
                updated_at REAL
            );

            INSERT INTO fact_events (
                id, event_id, timestamp, created_at, event_type, source,
                source_item_id, idempotency_key, memory_domain,
                cognition_eligible, retention_class, session_id, turn_id,
                user_id, content, author_type, content_type, importance_score,
                media_path, metadata_json, evidence_status, evidence_class,
                evidence_rule_version, l1_retrieval_scope, deleted_at
            ) VALUES (
                1, 'may-5',
                CAST(strftime('%s', '2026-05-05 12:00:00', 'utc') AS REAL),
                CAST(strftime('%s', '2026-05-05 12:00:00', 'utc') AS REAL),
                'source_event', 'netease_music', 'source-1', 'idem-1', 2,
                1, 2, 'session-1', 'turn-1', 'user-1',
                'in-range event', 4, 1, 0.5, NULL,
                '{"timeline":{"source_app":"NetEase"}}', 2, 7,
                6, 2, NULL
            );

            INSERT INTO l1_event_embedding_state (
                event_id, embedding_status, embedding_profile_id, embedding_chunk_count,
                last_embedded_at, updated_at
            ) VALUES (
                'may-5', 3, 'profile-a', 2,
                CAST(strftime('%s', '2026-05-05 12:05:00', 'utc') AS REAL),
                CAST(strftime('%s', '2026-05-05 12:05:00', 'utc') AS REAL)
            );

            INSERT INTO fact_events (
                id, event_id, timestamp, created_at, event_type, source,
                source_item_id, idempotency_key, memory_domain,
                cognition_eligible, retention_class, session_id, turn_id,
                user_id, content, author_type, content_type, importance_score,
                media_path, metadata_json, evidence_status, evidence_class,
                evidence_rule_version, l1_retrieval_scope, deleted_at
            ) VALUES (
                2, 'may-7',
                CAST(strftime('%s', '2026-05-07 12:00:00', 'utc') AS REAL),
                CAST(strftime('%s', '2026-05-07 12:00:00', 'utc') AS REAL),
                'source_event', 'netease_music', 'source-2', 'idem-2', 2,
                1, 2, 'session-1', 'turn-2', 'user-1',
                'out-of-range event', 4, 1, 0.5, NULL,
                '{}', 1, 7, 6, 1, NULL
            );

            INSERT INTO l1_event_embedding_state (
                event_id, embedding_status, embedding_profile_id, embedding_chunk_count,
                last_embedded_at, updated_at
            ) VALUES (
                'may-7', 2, 'profile-a', 0, NULL,
                CAST(strftime('%s', '2026-05-07 12:00:00', 'utc') AS REAL)
            );
            "#,
        )
        .unwrap();
    }

    #[test]
    fn build_l1_events_response_filters_iso_dates_and_returns_embedding_fields() {
        let _base_dir = isolated_base_dir("date-filter");
        seed_l1_events_for_date_filter();

        let response = build_l1_events_response(&L1EventsQuery {
            limit: Some(50),
            offset: None,
            event_id: None,
            event_type: None,
            user_id: None,
            session_id: None,
            query: None,
            source: None,
            source_item_id: None,
            idempotency_key: None,
            start_date: Some("2026-05-04".to_string()),
            end_date: Some("2026-05-06".to_string()),
        })
        .expect("read seeded L1 events");

        assert_eq!(response["total"], 1);
        let items = response["items"].as_array().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0]["event_id"], "may-5");
        assert_eq!(items[0]["correlation_id"], "may-5");
        assert_eq!(items[0]["memory_domain"], "external_activity");
        assert_eq!(items[0]["ingest_target"], "l1_only");
        assert_eq!(items[0]["tom_depth"], "none");
        assert_eq!(items[0]["retention_class"], "compressible");
        assert_eq!(items[0]["author_type"], "system");
        assert_eq!(items[0]["content_type"], "text");
        assert_eq!(items[0]["embedding_status"], "ready");
        assert_eq!(items[0]["embedding_profile_id"], "profile-a");
        assert_eq!(items[0]["embedding_chunk_count"], 2);
        assert_eq!(items[0]["evidence_status"], "classified");
        assert_eq!(items[0]["evidence_class"], "external_observation");
        assert_eq!(items[0]["l1_retrieval_scope"], "fact_authoritative");
        assert_eq!(
            items[0]["metadata_json"]["timeline"]["source_app"],
            "NetEase"
        );
    }

    #[test]
    fn build_l1_events_response_fails_when_store_is_missing() {
        let _base_dir = isolated_base_dir("missing-store");

        let result = build_l1_events_response(&L1EventsQuery {
            limit: Some(50),
            offset: None,
            event_id: None,
            event_type: None,
            user_id: None,
            session_id: None,
            query: None,
            source: None,
            source_item_id: None,
            idempotency_key: None,
            start_date: None,
            end_date: None,
        });

        assert_eq!(result.unwrap_err(), L1EventsReadError::StoreUnavailable);
    }
}
