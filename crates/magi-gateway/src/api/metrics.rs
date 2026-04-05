use axum::extract::Query;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::db;

#[derive(Deserialize)]
pub struct SummaryQuery {
    pub days: Option<i64>,
    pub model_limit: Option<i64>,
}

#[derive(Deserialize)]
pub struct TimeseriesQuery {
    pub days: Option<i64>,
}

/// Native GET /api/metrics/llm/usage/summary handler.
pub async fn llm_usage_summary(Query(params): Query<SummaryQuery>) -> Json<Value> {
    let days = params.days.unwrap_or(7).clamp(1, 365);
    let model_limit = params.model_limit.unwrap_or(8).clamp(1, 50);
    let result = tokio::task::spawn_blocking(move || query_summary(days, model_limit))
        .await
        .unwrap_or_else(|_| empty_summary(7));
    Json(json!({
        "success": true,
        "message": "LLM usage summary loaded",
        "data": result,
    }))
}

/// Native GET /api/metrics/llm/usage/timeseries handler.
pub async fn llm_usage_timeseries(Query(params): Query<TimeseriesQuery>) -> Json<Value> {
    let days = params.days.unwrap_or(7).clamp(1, 365);
    let result = tokio::task::spawn_blocking(move || query_timeseries(days))
        .await
        .unwrap_or_else(|_| json!({"window_days": days, "points": []}));
    Json(json!({
        "success": true,
        "message": "LLM usage timeseries loaded",
        "data": result,
    }))
}

fn now_epoch() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn open_llm_usage_db() -> Option<Connection> {
    let path = db::llm_usage_db_path();
    if !path.exists() {
        return None;
    }
    Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()
}

fn empty_summary(days: i64) -> Value {
    json!({
        "window_days": days,
        "totals": {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "calls_with_usage": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "avg_latency_ms": 0.0,
            "avg_ttft_ms": null,
            "total_cost_usd": 0.0,
        },
        "providers": [],
        "models": [],
        "request_kinds": [],
    })
}

fn query_summary(days: i64, model_limit: i64) -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => return empty_summary(days),
    };
    let cutoff = now_epoch() - (days as f64 * 86400.0);

    // Totals
    let totals = match conn.query_row(
        "SELECT \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN usage_available = 1 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1",
        rusqlite::params![cutoff],
        |row| {
            let avg_ttft: f64 = row.get(8)?;
            Ok(json!({
                "total_calls": row.get::<_, i64>(0)?,
                "successful_calls": row.get::<_, i64>(1)?,
                "failed_calls": row.get::<_, i64>(2)?,
                "calls_with_usage": row.get::<_, i64>(3)?,
                "prompt_tokens": row.get::<_, i64>(4)?,
                "completion_tokens": row.get::<_, i64>(5)?,
                "total_tokens": row.get::<_, i64>(6)?,
                "avg_latency_ms": (row.get::<_, f64>(7)? * 100.0).round() / 100.0,
                "avg_ttft_ms": if avg_ttft > 0.0 { json!((avg_ttft * 100.0).round() / 100.0) } else { Value::Null },
                "total_cost_usd": (row.get::<_, f64>(9)? * 10000.0).round() / 10000.0,
            }))
        },
    ) {
        Ok(v) => v,
        Err(_) => return empty_summary(days),
    };

    // Provider breakdown
    let providers = query_grouped_usage(
        &conn,
        "SELECT provider, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY provider ORDER BY total_tokens DESC, calls DESC",
        rusqlite::params![cutoff],
        &["provider"],
    );

    // Model breakdown
    let models = query_grouped_usage(
        &conn,
        "SELECT provider, model, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY provider, model ORDER BY total_tokens DESC, calls DESC LIMIT ?2",
        rusqlite::params![cutoff, model_limit],
        &["provider", "model"],
    );

    // Request kind breakdown
    let request_kinds = query_grouped_usage(
        &conn,
        "SELECT request_kind, \
            COUNT(*), \
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), \
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY request_kind ORDER BY total_tokens DESC, calls DESC",
        rusqlite::params![cutoff],
        &["request_kind"],
    );

    json!({
        "window_days": days,
        "totals": totals,
        "providers": providers,
        "models": models,
        "request_kinds": request_kinds,
    })
}

/// Generic grouped usage query. `label_cols` are the leading string columns.
fn query_grouped_usage(
    conn: &Connection,
    query: &str,
    params: &[&dyn rusqlite::types::ToSql],
    label_cols: &[&str],
) -> Vec<Value> {
    let mut stmt = match conn.prepare(query) {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let n = label_cols.len();
    stmt.query_map(params, |row| {
        let mut obj = serde_json::Map::new();
        for (i, col) in label_cols.iter().enumerate() {
            obj.insert(
                col.to_string(),
                json!(row.get::<_, String>(i)?),
            );
        }
        let avg_ttft: f64 = row.get(n + 7)?;
        obj.insert("calls".into(), json!(row.get::<_, i64>(n)?));
        obj.insert("successful_calls".into(), json!(row.get::<_, i64>(n + 1)?));
        obj.insert("failed_calls".into(), json!(row.get::<_, i64>(n + 2)?));
        obj.insert("prompt_tokens".into(), json!(row.get::<_, i64>(n + 3)?));
        obj.insert("completion_tokens".into(), json!(row.get::<_, i64>(n + 4)?));
        obj.insert("total_tokens".into(), json!(row.get::<_, i64>(n + 5)?));
        obj.insert(
            "avg_latency_ms".into(),
            json!((row.get::<_, f64>(n + 6)? * 100.0).round() / 100.0),
        );
        obj.insert(
            "avg_ttft_ms".into(),
            if avg_ttft > 0.0 {
                json!((avg_ttft * 100.0).round() / 100.0)
            } else {
                json!(0.0)
            },
        );
        obj.insert(
            "cost_usd".into(),
            json!((row.get::<_, f64>(n + 8)? * 10000.0).round() / 10000.0),
        );
        Ok(Value::Object(obj))
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn query_timeseries(days: i64) -> Value {
    let conn = match open_llm_usage_db() {
        Some(c) => c,
        None => return json!({"window_days": days, "points": []}),
    };
    let cutoff = now_epoch() - (days as f64 * 86400.0);
    let mut stmt = match conn.prepare(
        "SELECT \
            strftime('%Y-%m-%d', datetime(created_at, 'unixepoch', 'localtime')) AS day, \
            COUNT(*), \
            COALESCE(SUM(prompt_tokens), 0), \
            COALESCE(SUM(completion_tokens), 0), \
            COALESCE(SUM(total_tokens), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1 \
         GROUP BY day ORDER BY day ASC",
    ) {
        Ok(s) => s,
        Err(_) => return json!({"window_days": days, "points": []}),
    };
    let points: Vec<Value> = stmt
        .query_map(rusqlite::params![cutoff], |row| {
            Ok(json!({
                "day": row.get::<_, String>(0)?,
                "calls": row.get::<_, i64>(1)?,
                "prompt_tokens": row.get::<_, i64>(2)?,
                "completion_tokens": row.get::<_, i64>(3)?,
                "total_tokens": row.get::<_, i64>(4)?,
                "cost_usd": (row.get::<_, f64>(5)? * 10000.0).round() / 10000.0,
            }))
        })
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    json!({
        "window_days": days,
        "points": points,
    })
}
