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
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cache_write_1h_tokens": 0,
            "cache_hit_rate": 0.0,
            "avg_latency_ms": 0.0,
            "avg_ttft_ms": null,
            "total_cost_usd": 0.0,
            "cost_by_currency": [],
        },
        "providers": [],
        "models": [],
        "request_kinds": [],
    })
}

const PROVIDER_BREAKDOWN_QUERY: &str = "SELECT provider, \
    COUNT(*) AS calls, \
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls, \
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls, \
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, \
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens, \
    COALESCE(SUM(total_tokens), 0) AS total_tokens, \
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens, \
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens, \
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens, \
    CASE WHEN COALESCE(SUM(prompt_tokens), 0) > 0 \
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2) \
        ELSE 0 END AS cache_hit_rate, \
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, \
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms, \
    COALESCE(SUM(cost_usd), 0) AS cost_usd, \
    MAX(cost_currency) AS cost_currency \
 FROM llm_usage WHERE created_at >= ?1 \
 GROUP BY provider ORDER BY total_tokens DESC, calls DESC";

const MODEL_BREAKDOWN_QUERY: &str = "SELECT provider, model, \
    COUNT(*) AS calls, \
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls, \
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls, \
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, \
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens, \
    COALESCE(SUM(total_tokens), 0) AS total_tokens, \
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens, \
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens, \
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens, \
    CASE WHEN COALESCE(SUM(prompt_tokens), 0) > 0 \
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2) \
        ELSE 0 END AS cache_hit_rate, \
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, \
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms, \
    COALESCE(SUM(cost_usd), 0) AS cost_usd, \
    MAX(cost_currency) AS cost_currency \
 FROM llm_usage WHERE created_at >= ?1 \
 GROUP BY provider, model ORDER BY total_tokens DESC, calls DESC LIMIT ?2";

const REQUEST_KIND_BREAKDOWN_QUERY: &str = "SELECT request_kind, \
    COUNT(*) AS calls, \
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_calls, \
    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_calls, \
    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, \
    COALESCE(SUM(completion_tokens), 0) AS completion_tokens, \
    COALESCE(SUM(total_tokens), 0) AS total_tokens, \
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens, \
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens, \
    COALESCE(SUM(cache_write_1h_tokens), 0) AS cache_write_1h_tokens, \
    CASE WHEN COALESCE(SUM(prompt_tokens), 0) > 0 \
        THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2) \
        ELSE 0 END AS cache_hit_rate, \
    COALESCE(AVG(latency_ms), 0) AS avg_latency_ms, \
    COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0) AS avg_ttft_ms, \
    COALESCE(SUM(cost_usd), 0) AS cost_usd, \
    MAX(cost_currency) AS cost_currency \
 FROM llm_usage WHERE created_at >= ?1 \
 GROUP BY request_kind ORDER BY total_tokens DESC, calls DESC";

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
            COALESCE(SUM(cache_read_tokens), 0), \
            COALESCE(SUM(cache_write_tokens), 0), \
            COALESCE(SUM(cache_write_1h_tokens), 0), \
            CASE WHEN COALESCE(SUM(prompt_tokens), 0) > 0 \
                THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2) \
                ELSE 0 END, \
            COALESCE(AVG(latency_ms), 0), \
            COALESCE(AVG(CASE WHEN ttft_ms > 0 THEN ttft_ms END), 0), \
            COALESCE(SUM(cost_usd), 0) \
         FROM llm_usage WHERE created_at >= ?1",
        rusqlite::params![cutoff],
        |row| {
            let avg_ttft: f64 = row.get(12)?;
            Ok(json!({
                "total_calls": row.get::<_, i64>(0)?,
                "successful_calls": row.get::<_, i64>(1)?,
                "failed_calls": row.get::<_, i64>(2)?,
                "calls_with_usage": row.get::<_, i64>(3)?,
                "prompt_tokens": row.get::<_, i64>(4)?,
                "completion_tokens": row.get::<_, i64>(5)?,
                "total_tokens": row.get::<_, i64>(6)?,
                "cache_read_tokens": row.get::<_, i64>(7)?,
                "cache_write_tokens": row.get::<_, i64>(8)?,
                "cache_write_1h_tokens": row.get::<_, i64>(9)?,
                "cache_hit_rate": (row.get::<_, f64>(10)? * 100.0).round() / 100.0,
                "avg_latency_ms": (row.get::<_, f64>(11)? * 100.0).round() / 100.0,
                "avg_ttft_ms": if avg_ttft > 0.0 { json!((avg_ttft * 100.0).round() / 100.0) } else { Value::Null },
                "total_cost_usd": (row.get::<_, f64>(13)? * 10000.0).round() / 10000.0,
            }))
        },
    ) {
        Ok(mut v) => {
            // Per-currency cost breakdown (native billing currencies).
            let cost_by_currency: Vec<Value> = match conn.prepare(
                "SELECT cost_currency, COALESCE(SUM(cost_usd), 0) \
                 FROM llm_usage WHERE created_at >= ?1 AND cost_currency IS NOT NULL \
                 GROUP BY cost_currency ORDER BY 2 DESC",
            ) {
                Ok(mut stmt) => stmt
                    .query_map(rusqlite::params![cutoff], |row| {
                        Ok(json!({
                            "currency": row.get::<_, String>(0)?,
                            "amount": (row.get::<_, f64>(1)? * 10000.0).round() / 10000.0,
                        }))
                    })
                    .ok()
                    .map(|iter| iter.filter_map(|r| r.ok()).collect())
                    .unwrap_or_default(),
                Err(_) => vec![],
            };
            if let Value::Object(ref mut m) = v {
                m.insert("cost_by_currency".to_string(), Value::Array(cost_by_currency));
            }
            v
        }
        Err(_) => return empty_summary(days),
    };

    // Provider breakdown
    let providers = query_grouped_usage(
        &conn,
        PROVIDER_BREAKDOWN_QUERY,
        rusqlite::params![cutoff],
        &["provider"],
    );

    // Model breakdown
    let models = query_grouped_usage(
        &conn,
        MODEL_BREAKDOWN_QUERY,
        rusqlite::params![cutoff, model_limit],
        &["provider", "model"],
    );

    // Request kind breakdown
    let request_kinds = query_grouped_usage(
        &conn,
        REQUEST_KIND_BREAKDOWN_QUERY,
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
            obj.insert(col.to_string(), json!(row.get::<_, String>(i)?));
        }
        let avg_ttft: f64 = row.get(n + 11)?;
        obj.insert("calls".into(), json!(row.get::<_, i64>(n)?));
        obj.insert("successful_calls".into(), json!(row.get::<_, i64>(n + 1)?));
        obj.insert("failed_calls".into(), json!(row.get::<_, i64>(n + 2)?));
        obj.insert("prompt_tokens".into(), json!(row.get::<_, i64>(n + 3)?));
        obj.insert("completion_tokens".into(), json!(row.get::<_, i64>(n + 4)?));
        obj.insert("total_tokens".into(), json!(row.get::<_, i64>(n + 5)?));
        obj.insert("cache_read_tokens".into(), json!(row.get::<_, i64>(n + 6)?));
        obj.insert(
            "cache_write_tokens".into(),
            json!(row.get::<_, i64>(n + 7)?),
        );
        obj.insert(
            "cache_write_1h_tokens".into(),
            json!(row.get::<_, i64>(n + 8)?),
        );
        obj.insert(
            "cache_hit_rate".into(),
            json!((row.get::<_, f64>(n + 9)? * 100.0).round() / 100.0),
        );
        obj.insert(
            "avg_latency_ms".into(),
            json!((row.get::<_, f64>(n + 10)? * 100.0).round() / 100.0),
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
            json!((row.get::<_, f64>(n + 12)? * 10000.0).round() / 10000.0),
        );
        let cost_currency: Option<String> = row.get(n + 13)?;
        obj.insert("cost_currency".into(), json!(cost_currency));
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
            COALESCE(SUM(cache_read_tokens), 0), \
            COALESCE(SUM(cache_write_tokens), 0), \
            COALESCE(SUM(cache_write_1h_tokens), 0), \
            CASE WHEN COALESCE(SUM(prompt_tokens), 0) > 0 \
                THEN ROUND(COALESCE(SUM(cache_read_tokens), 0) * 100.0 / SUM(prompt_tokens), 2) \
                ELSE 0 END, \
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
                "cache_read_tokens": row.get::<_, i64>(5)?,
                "cache_write_tokens": row.get::<_, i64>(6)?,
                "cache_write_1h_tokens": row.get::<_, i64>(7)?,
                "cache_hit_rate": (row.get::<_, f64>(8)? * 100.0).round() / 100.0,
                "cost_usd": (row.get::<_, f64>(9)? * 10000.0).round() / 10000.0,
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

#[cfg(test)]
mod tests {
    use super::{
        query_grouped_usage, MODEL_BREAKDOWN_QUERY, PROVIDER_BREAKDOWN_QUERY,
        REQUEST_KIND_BREAKDOWN_QUERY,
    };
    use rusqlite::Connection;

    fn setup_llm_usage_table(conn: &Connection) {
        conn.execute_batch(
            "
            CREATE TABLE llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                request_kind TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_tokens INTEGER NOT NULL DEFAULT 0,
                cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
                usage_available INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                ttft_ms INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                cost_currency TEXT,
                success INTEGER NOT NULL DEFAULT 1,
                error TEXT,
                correlation_id TEXT,
                session_id TEXT,
                turn_id TEXT,
                agent_id TEXT,
                created_at REAL NOT NULL
            );

            INSERT INTO llm_usage (
                request_id, provider, model, request_kind, prompt_tokens, completion_tokens,
                total_tokens, cache_read_tokens, cache_write_tokens, cache_write_1h_tokens,
                usage_available, latency_ms, ttft_ms, cost_usd, cost_currency, success, created_at
            ) VALUES
                ('req-1', 'openai', 'gpt-4.1', 'chat', 100, 40, 140, 80, 10, 0, 1, 1200, 300, 0.12, 'USD', 1, 1000),
                ('req-2', 'openai', 'gpt-4.1', 'chat', 50, 10, 60, 20, 5, 0, 1, 900, 250, 0.04, 'USD', 1, 1001),
                ('req-3', 'anthropic', 'claude-3-7-sonnet', 'function_calling:tools', 80, 20, 100, 10, 2, 1, 1, 1500, 0, 0.08, 'USD', 1, 1002);
            ",
        )
        .expect("create llm_usage test table");
    }

    #[test]
    fn grouped_usage_breakdowns_return_rows() {
        let conn = Connection::open_in_memory().expect("open in-memory db");
        setup_llm_usage_table(&conn);

        let providers = query_grouped_usage(
            &conn,
            PROVIDER_BREAKDOWN_QUERY,
            rusqlite::params![0.0],
            &["provider"],
        );
        let models = query_grouped_usage(
            &conn,
            MODEL_BREAKDOWN_QUERY,
            rusqlite::params![0.0, 8],
            &["provider", "model"],
        );
        let request_kinds = query_grouped_usage(
            &conn,
            REQUEST_KIND_BREAKDOWN_QUERY,
            rusqlite::params![0.0],
            &["request_kind"],
        );

        assert_eq!(providers.len(), 2);
        assert_eq!(providers[0]["provider"], "openai");
        assert_eq!(providers[0]["calls"], 2);
        assert_eq!(providers[0]["total_tokens"], 200);
        assert_eq!(providers[0]["cache_read_tokens"], 100);
        assert_eq!(providers[0]["cache_write_tokens"], 15);
        assert_eq!(providers[0]["cache_hit_rate"], 66.67);
        assert_eq!(providers[0]["cost_currency"], "USD");

        assert_eq!(models.len(), 2);
        assert_eq!(models[0]["provider"], "openai");
        assert_eq!(models[0]["model"], "gpt-4.1");
        assert_eq!(models[0]["total_tokens"], 200);

        assert_eq!(request_kinds.len(), 2);
        assert_eq!(request_kinds[0]["request_kind"], "chat");
        assert_eq!(request_kinds[0]["calls"], 2);
    }

    #[test]
    fn null_cost_currency_yields_json_null() {
        let conn = Connection::open_in_memory().expect("open in-memory db");
        setup_llm_usage_table(&conn);
        // Seed an unpriced provider (cost_currency left NULL).
        conn.execute(
            "INSERT INTO llm_usage (
                request_id, provider, model, request_kind, prompt_tokens, completion_tokens,
                total_tokens, usage_available, latency_ms, ttft_ms, cost_usd, success, created_at
            ) VALUES
                ('req-4', 'local', 'llama-3', 'chat', 5, 5, 10, 1, 100, 0, 0, 1, 1003)",
            [],
        )
        .expect("insert unpriced row");

        let providers = query_grouped_usage(
            &conn,
            PROVIDER_BREAKDOWN_QUERY,
            rusqlite::params![0.0],
            &["provider"],
        );
        let local = providers
            .iter()
            .find(|p| p["provider"] == "local")
            .expect("local provider row present");
        assert!(local["cost_currency"].is_null());
    }
}
