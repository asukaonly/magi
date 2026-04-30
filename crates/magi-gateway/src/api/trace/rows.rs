use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::HashMap;

pub(super) fn load_trace_turn(
    conn: &Connection,
    user_id: &str,
    session_id: &str,
    turn_id: &str,
) -> Option<HashMap<String, Value>> {
    let mut stmt = conn
        .prepare(
            "SELECT trace_id, turn_id, session_id, user_id, status, mode, \
             orchestration_id, started_at_ms, ended_at_ms, duration_ms, \
             user_message_preview, response_preview, error_summary, \
             continued_from_turn_id, continued_from_trace_id, \
             superseded_by_turn_id, supersession_reason \
             FROM trace_turns \
             WHERE user_id = ?1 AND session_id = ?2 AND turn_id = ?3 \
             LIMIT 1",
        )
        .ok()?;
    let names: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    let row = stmt
        .query_row(rusqlite::params![user_id, session_id, turn_id], |row| {
            let mut map = HashMap::new();
            for (i, name) in names.iter().enumerate() {
                map.insert(name.clone(), row_value(row, i));
            }
            Ok(map)
        })
        .ok()?;
    Some(row)
}

pub(super) fn load_trace_spans(conn: &Connection, trace_id: &str) -> Vec<HashMap<String, Value>> {
    if trace_id.is_empty() {
        return vec![];
    }
    load_rows(
        conn,
        "SELECT span_id, trace_id, turn_id, parent_span_id, node_type, name, \
         status, attempt_index, retry_count, iteration, execution_agent_id, \
         result_preview, error_text, started_at_ms, ended_at_ms, duration_ms \
         FROM trace_spans WHERE trace_id = ?1 \
         ORDER BY started_at_ms ASC, span_id ASC",
        rusqlite::params![trace_id],
    )
}

pub(super) fn load_detail_rows(
    conn: &Connection,
    table: &str,
    trace_id: &str,
) -> Vec<HashMap<String, Value>> {
    if trace_id.is_empty() {
        return vec![];
    }
    let query = format!("SELECT * FROM {} WHERE trace_id = ?1", table);
    load_rows(conn, &query, rusqlite::params![trace_id])
}

fn load_rows(
    conn: &Connection,
    query: &str,
    params: &[&dyn rusqlite::types::ToSql],
) -> Vec<HashMap<String, Value>> {
    let mut stmt = match conn.prepare(query) {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let names: Vec<String> = stmt.column_names().iter().map(|s| s.to_string()).collect();
    stmt.query_map(params, |row| {
        let mut map = HashMap::new();
        for (i, name) in names.iter().enumerate() {
            map.insert(name.clone(), row_value(row, i));
        }
        Ok(map)
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn row_value(row: &rusqlite::Row, idx: usize) -> Value {
    if let Ok(v) = row.get::<_, i64>(idx) {
        return json!(v);
    }
    if let Ok(v) = row.get::<_, f64>(idx) {
        return json!(v);
    }
    if let Ok(v) = row.get::<_, String>(idx) {
        return json!(v);
    }
    Value::Null
}
