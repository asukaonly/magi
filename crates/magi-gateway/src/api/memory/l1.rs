use axum::extract::Query;
use axum::Json;
use serde_json::{json, Value};

use crate::db;

use super::query::{clamp_limit, clamp_offset, L1EventsQuery, DEFAULT_LIMIT};

// ---------------------------------------------------------------------------
// L1 Events
// ---------------------------------------------------------------------------

/// GET /api/memory/l1/events — query fact_events from l1_events.db.
pub async fn list_l1_events(Query(params): Query<L1EventsQuery>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || build_l1_events_response(&params))
        .await
        .unwrap_or_else(|_| json!({"items": [], "total": 0, "limit": 50, "offset": 0}));
    Json(result)
}

fn build_l1_events_response(params: &L1EventsQuery) -> Value {
    let limit = clamp_limit(params.limit, DEFAULT_LIMIT);
    let offset = clamp_offset(params.offset);
    let path = db::l1_events_db_path();
    let conn = match db::open_readonly(&path) {
        Some(c) => c,
        None => return json!({"items": [], "total": 0, "limit": limit, "offset": offset}),
    };

    let mut where_parts = vec!["deleted_at IS NULL".to_string()];
    let mut bind: Vec<rusqlite::types::Value> = Vec::new();

    if let Some(ref v) = params.event_type {
        where_parts.push("event_type = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.event_id {
        where_parts.push("event_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.user_id {
        where_parts.push("user_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.session_id {
        where_parts.push("session_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source {
        where_parts.push("source = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.source_item_id {
        where_parts.push("source_item_id = ?".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }
    if let Some(ref v) = params.idempotency_key {
        where_parts.push("idempotency_key = ?".into());
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
        where_parts
            .push("event_id IN (SELECT event_id FROM l1_events_fts WHERE content MATCH ?)".into());
        bind.push(rusqlite::types::Value::Text(v.clone()));
    }

    let where_clause = where_parts.join(" AND ");

    // Count total matching rows
    let count_sql = format!("SELECT COUNT(*) FROM fact_events WHERE {}", where_clause);
    let count_refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();
    let total = db::count_rows(&conn, &count_sql, &count_refs);

    bind.push(rusqlite::types::Value::Integer(limit));
    bind.push(rusqlite::types::Value::Integer(offset));

    let sql = format!(
        "SELECT id, event_id, correlation_id, timestamp, created_at, event_type, \
         source, source_item_id, idempotency_key, memory_domain, ingest_target, \
         cognition_eligible, tom_depth, retention_class, session_id, turn_id, \
         user_id, task_id, content, author_type, content_type, importance_score, \
         level, media_path, metadata_json, embedding_status, embedding_profile_id, \
         embedding_chunk_count, last_embedded_at, deleted_at \
         FROM fact_events WHERE {} ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        where_clause
    );
    let refs: Vec<&dyn rusqlite::types::ToSql> = bind
        .iter()
        .map(|v| v as &dyn rusqlite::types::ToSql)
        .collect();

    let items = db::query_to_json_array(&conn, &sql, &refs);
    json!({"items": items, "total": total, "limit": limit, "offset": offset})
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
    use std::sync::{Mutex, MutexGuard, OnceLock};

    use super::*;

    static TEST_COUNTER: AtomicU32 = AtomicU32::new(0);
    static BASE_DIR_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

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
        let lock = BASE_DIR_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .expect("lock L1 gateway test base dir");
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
                correlation_id TEXT,
                timestamp REAL NOT NULL,
                created_at REAL,
                event_type TEXT,
                source TEXT,
                source_item_id TEXT,
                idempotency_key TEXT,
                memory_domain TEXT,
                ingest_target TEXT,
                cognition_eligible INTEGER,
                tom_depth TEXT,
                retention_class TEXT,
                session_id TEXT,
                turn_id TEXT,
                user_id TEXT,
                task_id TEXT,
                content TEXT,
                author_type TEXT,
                content_type TEXT,
                importance_score REAL,
                level INTEGER,
                media_path TEXT,
                metadata_json TEXT,
                embedding_status TEXT,
                embedding_profile_id TEXT,
                embedding_chunk_count INTEGER,
                last_embedded_at REAL,
                deleted_at REAL
            );

            INSERT INTO fact_events (
                id, event_id, correlation_id, timestamp, created_at, event_type, source,
                source_item_id, idempotency_key, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id,
                user_id, task_id, content, author_type, content_type, importance_score,
                level, media_path, metadata_json, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, deleted_at
            ) VALUES (
                1, 'may-5', NULL,
                CAST(strftime('%s', '2026-05-05 12:00:00', 'utc') AS REAL),
                CAST(strftime('%s', '2026-05-05 12:00:00', 'utc') AS REAL),
                'sensor_event', 'netease_music', 'source-1', 'idem-1', 'external',
                'observation', 1, 'none', 'short', 'session-1', 'turn-1', 'user-1',
                NULL, 'in-range event', 'system', 'text', 0.5, 20, NULL,
                '{"timeline":{"source_app":"NetEase"}}', 'ready', 'profile-a', 2,
                CAST(strftime('%s', '2026-05-05 12:05:00', 'utc') AS REAL), NULL
            );

            INSERT INTO fact_events (
                id, event_id, correlation_id, timestamp, created_at, event_type, source,
                source_item_id, idempotency_key, memory_domain, ingest_target,
                cognition_eligible, tom_depth, retention_class, session_id, turn_id,
                user_id, task_id, content, author_type, content_type, importance_score,
                level, media_path, metadata_json, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, deleted_at
            ) VALUES (
                2, 'may-7', NULL,
                CAST(strftime('%s', '2026-05-07 12:00:00', 'utc') AS REAL),
                CAST(strftime('%s', '2026-05-07 12:00:00', 'utc') AS REAL),
                'sensor_event', 'netease_music', 'source-2', 'idem-2', 'external',
                'observation', 1, 'none', 'short', 'session-1', 'turn-2', 'user-1',
                NULL, 'out-of-range event', 'system', 'text', 0.5, 20, NULL,
                '{}', 'pending', 'profile-a', 0, NULL, NULL
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
        });

        assert_eq!(response["total"], 1);
        let items = response["items"].as_array().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0]["event_id"], "may-5");
        assert_eq!(items[0]["embedding_status"], "ready");
        assert_eq!(items[0]["embedding_profile_id"], "profile-a");
        assert_eq!(items[0]["embedding_chunk_count"], 2);
        assert_eq!(
            items[0]["metadata_json"]["timeline"]["source_app"],
            "NetEase"
        );
    }
}
