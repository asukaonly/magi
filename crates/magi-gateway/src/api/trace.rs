use axum::extract::Query;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

#[derive(Deserialize)]
pub struct TraceQuery {
    pub user_id: Option<String>,
    pub session_id: Option<String>,
    pub turn_id: Option<String>,
}

/// Native GET /api/messages/trace handler — reads runtime_trace.db directly.
pub async fn get_trace(Query(params): Query<TraceQuery>) -> Json<Value> {
    let user_id = params
        .user_id
        .unwrap_or_else(|| "default_user".to_string());
    let session_id = match &params.session_id {
        Some(s) if !s.is_empty() => s.clone(),
        _ => return Json(json!({"success": false, "trace": null})),
    };
    let turn_id = match &params.turn_id {
        Some(t) if !t.is_empty() => t.clone(),
        _ => return Json(json!({"success": false, "trace": null})),
    };

    let result =
        tokio::task::spawn_blocking(move || build_trace_snapshot(&user_id, &session_id, &turn_id))
            .await
            .unwrap_or_else(|_| json!({"success": false, "trace": null}));
    Json(result)
}

pub(super) fn build_trace_snapshot(user_id: &str, session_id: &str, turn_id: &str) -> Value {
    let trace_path = db::runtime_trace_db_path();
    if !trace_path.exists() {
        return json!({"success": false, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null});
    }
    let conn = match Connection::open_with_flags(&trace_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return json!({"success": false, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null}),
    };

    // Load trace_turn
    let turn = match load_trace_turn(&conn, user_id, session_id, turn_id) {
        Some(t) => t,
        None => return json!({"success": true, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null}),
    };

    let trace_id = turn
        .get("trace_id")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let spans = load_trace_spans(&conn, &trace_id);
    let llm_calls = load_detail_rows(&conn, "trace_llm_calls", &trace_id);
    let tool_calls = load_detail_rows(&conn, "trace_tools", &trace_id);

    let snapshot = assemble_snapshot(user_id, session_id, &turn, &spans, &llm_calls, &tool_calls);
    json!({
        "success": true,
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "trace": snapshot,
    })
}

fn load_trace_turn(
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
    let names: Vec<String> = stmt
        .column_names()
        .iter()
        .map(|s| s.to_string())
        .collect();
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

fn load_trace_spans(conn: &Connection, trace_id: &str) -> Vec<HashMap<String, Value>> {
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

fn load_detail_rows(
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
    let names: Vec<String> = stmt
        .column_names()
        .iter()
        .map(|s| s.to_string())
        .collect();
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
    // Try integer first, then float, then string, then null
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

fn ms_to_seconds(val: &Value) -> Option<f64> {
    val.as_i64().map(|ms| ms as f64 / 1000.0)
}

fn opt_str(val: &Value) -> Option<&str> {
    val.as_str().filter(|s| !s.is_empty())
}

fn safe_int(val: &Value, default: i64) -> i64 {
    val.as_i64().unwrap_or(default)
}

fn normalize_status(raw: &str) -> &str {
    match raw {
        "ok" | "success" | "succeeded" | "done" => "completed",
        "error" | "errored" | "timeout" | "timed_out" => "failed",
        "" => "running",
        other => other,
    }
}

fn is_terminal(status: &str) -> bool {
    matches!(status, "completed" | "failed" | "cancelled" | "skipped")
}

fn map_trace_kind(node_type: &str) -> &str {
    match node_type {
        "turn" => "root",
        "orchestration_plan" | "plan" => "planning",
        "worker" | "subtask" | "subtask_group" => "worker",
        "tool_call" | "tool" => "tool",
        "llm_call" | "llm" => "llm",
        _ => "step",
    }
}

fn default_trace_label(node_type: &str) -> &str {
    match node_type {
        "turn" => "Turn",
        "plan" | "orchestration_plan" => "Planning",
        "tool_call" | "tool" => "Tool call",
        "llm_call" | "llm" => "LLM call",
        "worker" | "subtask" => "Worker",
        _ => "Step",
    }
}

fn resolve_result_preview(
    span: &HashMap<String, Value>,
    llm_call: Option<&HashMap<String, Value>>,
    tool_call: Option<&HashMap<String, Value>>,
) -> String {
    let preview = span
        .get("result_preview")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if !preview.is_empty() {
        return preview.to_string();
    }
    if let Some(tc) = tool_call {
        let p = tc
            .get("result_preview")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !p.is_empty() {
            return p.to_string();
        }
    }
    if let Some(lc) = llm_call {
        let p = lc
            .get("response_preview")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !p.is_empty() {
            return p.to_string();
        }
    }
    String::new()
}

fn build_trace_node(
    span: &HashMap<String, Value>,
    llm_call: Option<&HashMap<String, Value>>,
    tool_call: Option<&HashMap<String, Value>>,
) -> Value {
    let node_type = span
        .get("node_type")
        .and_then(|v| v.as_str())
        .unwrap_or("step");
    let span_id = span.get("span_id").and_then(|v| v.as_str()).unwrap_or("");

    let mut metadata = json!({
        "trace_id": span.get("trace_id"),
        "span_id": span_id,
        "parent_span_id": span.get("parent_span_id"),
        "node_type": node_type,
        "attempt_index": safe_int(span.get("attempt_index").unwrap_or(&Value::Null), 1),
        "retry_count": safe_int(span.get("retry_count").unwrap_or(&Value::Null), 0),
        "iteration": safe_int(span.get("iteration").unwrap_or(&Value::Null), 0),
        "duration_ms": safe_int(span.get("duration_ms").unwrap_or(&Value::Null), 0),
        "execution_agent_id": span.get("execution_agent_id"),
    });

    if let Some(lc) = llm_call {
        metadata["provider"] = lc.get("provider").cloned().unwrap_or(Value::Null);
        metadata["model"] = lc.get("model").cloned().unwrap_or(Value::Null);
        metadata["input_tokens"] = json!(safe_int(
            lc.get("input_tokens").unwrap_or(&Value::Null),
            0
        ));
        metadata["output_tokens"] = json!(safe_int(
            lc.get("output_tokens").unwrap_or(&Value::Null),
            0
        ));
        metadata["reasoning_tokens"] = json!(safe_int(
            lc.get("reasoning_tokens").unwrap_or(&Value::Null),
            0
        ));
        metadata["cache_read_tokens"] = json!(safe_int(
            lc.get("cache_read_tokens").unwrap_or(&Value::Null),
            0
        ));
        metadata["cache_write_tokens"] = json!(safe_int(
            lc.get("cache_write_tokens").unwrap_or(&Value::Null),
            0
        ));
        metadata["thinking_enabled"] = json!(lc
            .get("thinking_enabled")
            .and_then(|v| v.as_i64())
            .unwrap_or(0)
            != 0);
    }

    if let Some(tc) = tool_call {
        metadata["tool_call_id"] = tc.get("tool_call_id").cloned().unwrap_or(Value::Null);
        metadata["tool_name"] = tc.get("tool_name").cloned().unwrap_or(Value::Null);
        metadata["arguments"] = tc
            .get("arguments_json")
            .and_then(|v| v.as_str())
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or(json!({}));
        metadata["execution_time"] = tc.get("execution_time_ms").cloned().unwrap_or(Value::Null);
    }

    let status_raw = span
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("running");
    let error_text = span
        .get("error_text")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .or_else(|| {
            tool_call.and_then(|tc| {
                tc.get("error_message")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
            })
        });

    json!({
        "id": span_id,
        "kind": map_trace_kind(node_type),
        "label": span.get("name").and_then(|v| v.as_str()).unwrap_or(default_trace_label(node_type)),
        "status": normalize_status(status_raw),
        "started_at": ms_to_seconds(span.get("started_at_ms").unwrap_or(&Value::Null)),
        "ended_at": ms_to_seconds(span.get("ended_at_ms").unwrap_or(&Value::Null)),
        "result_preview": resolve_result_preview(span, llm_call, tool_call),
        "error": error_text,
        "metadata": metadata,
        "children": [],
    })
}

fn assemble_snapshot(
    user_id: &str,
    session_id: &str,
    turn: &HashMap<String, Value>,
    spans: &[HashMap<String, Value>],
    llm_calls: &[HashMap<String, Value>],
    tool_calls: &[HashMap<String, Value>],
) -> Value {
    let turn_id = turn
        .get("turn_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let trace_id = turn
        .get("trace_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let status_raw = turn
        .get("status")
        .and_then(|v| v.as_str())
        .unwrap_or("running");
    let status = normalize_status(status_raw);
    let mode = turn
        .get("mode")
        .and_then(|v| v.as_str())
        .unwrap_or("function_calling");
    let started_at = ms_to_seconds(turn.get("started_at_ms").unwrap_or(&Value::Null));
    let ended_at = if is_terminal(status) {
        ms_to_seconds(turn.get("ended_at_ms").unwrap_or(&Value::Null))
    } else {
        None
    };

    // Index llm/tool calls by span_id
    let llm_by_span: HashMap<&str, &HashMap<String, Value>> = llm_calls
        .iter()
        .filter_map(|lc| {
            lc.get("span_id")
                .and_then(|v| v.as_str())
                .map(|sid| (sid, lc))
        })
        .collect();
    let tool_by_span: HashMap<&str, &HashMap<String, Value>> = tool_calls
        .iter()
        .filter_map(|tc| {
            tc.get("span_id")
                .and_then(|v| v.as_str())
                .map(|sid| (sid, tc))
        })
        .collect();

    // Build nodes by span_id
    let mut node_by_id: HashMap<String, Value> = HashMap::new();
    let mut children_by_parent: HashMap<Option<String>, Vec<String>> = HashMap::new();

    for span in spans {
        let span_id = span
            .get("span_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if span_id.is_empty() {
            continue;
        }
        let node = build_trace_node(span, llm_by_span.get(span_id.as_str()).copied(), tool_by_span.get(span_id.as_str()).copied());
        node_by_id.insert(span_id.clone(), node);

        let parent = span
            .get("parent_span_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        children_by_parent
            .entry(parent)
            .or_default()
            .push(span_id);
    }

    // Attach children to parents
    for (parent_id, child_ids) in &children_by_parent {
        if let Some(pid) = parent_id {
            let mut sorted_children: Vec<Value> = child_ids
                .iter()
                .filter_map(|cid| node_by_id.remove(cid))
                .collect();
            sorted_children
                .sort_by(|a, b| {
                    let sa = a.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    let sb = b.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    sa.partial_cmp(&sb).unwrap_or(std::cmp::Ordering::Equal)
                });
            if let Some(parent) = node_by_id.get_mut(pid) {
                if let Some(arr) = parent.get_mut("children").and_then(|v| v.as_array_mut()) {
                    arr.extend(sorted_children);
                }
            } else {
                // Parent not found, re-insert children for top-level collection
                for child in sorted_children {
                    let cid = child.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    if !cid.is_empty() {
                        node_by_id.insert(cid, child);
                    }
                }
            }
        }
    }

    // Collect top-level nodes (those with parent=None or parent=turn_span_id)
    let turn_span_id = format!("{}:turn", turn_id);
    let mut top_ids: Vec<String> = children_by_parent
        .get(&None)
        .cloned()
        .unwrap_or_default();
    // If turn node exists, its children are also top-level
    let turn_node = node_by_id.remove(&turn_span_id);
    if turn_node.is_none() {
        if let Some(turn_children) = children_by_parent.get(&Some(turn_span_id.clone())) {
            top_ids.extend(turn_children.clone());
        }
    }
    // Remove the turn span itself from top-level
    top_ids.retain(|id| id != &turn_span_id);

    let mut top_level: Vec<Value> = top_ids
        .iter()
        .filter_map(|id| node_by_id.remove(id))
        .collect();
    // Also add children from the turn node itself
    if let Some(tn) = &turn_node {
        if let Some(arr) = tn.get("children").and_then(|v| v.as_array()) {
            top_level.extend(arr.clone());
        }
    }
    top_level.sort_by(|a, b| {
        let sa = a.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let sb = b.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        sa.partial_cmp(&sb).unwrap_or(std::cmp::Ordering::Equal)
    });

    // Count steps
    let (active, completed, failed) = count_steps_in_children(&top_level);
    let duration = match (started_at, ended_at) {
        (Some(s), Some(e)) => (e - s).max(0.0),
        _ => 0.0,
    };

    let root = json!({
        "id": format!("{}:root", turn_id),
        "kind": "root",
        "label": "Tool chain",
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "result_preview": turn.get("response_preview").and_then(|v| v.as_str()).unwrap_or(""),
        "error": opt_str(turn.get("error_summary").unwrap_or(&Value::Null)),
        "metadata": {
            "turn_id": turn_id,
            "trace_id": if trace_id.is_empty() { format!("trace:{}", turn_id) } else { trace_id.to_string() },
            "normalized_trace": true,
        },
        "children": top_level,
    });

    let summary = json!({
        "turn_id": turn_id,
        "mode": mode,
        "status": status,
        "headline": build_headline(mode, status, active, completed),
        "active_steps": active,
        "completed_steps": completed,
        "failed_steps": failed,
        "duration_seconds": (duration * 1000.0).round() / 1000.0,
        "trace_available": !top_level.is_empty(),
        "orchestration_id": opt_str(turn.get("orchestration_id").unwrap_or(&Value::Null)),
        "plan_summary": null,
        "continued_from_turn_id": opt_str(turn.get("continued_from_turn_id").unwrap_or(&Value::Null)),
        "continued_from_trace_id": opt_str(turn.get("continued_from_trace_id").unwrap_or(&Value::Null)),
        "superseded_by_turn_id": opt_str(turn.get("superseded_by_turn_id").unwrap_or(&Value::Null)),
        "supersession_reason": opt_str(turn.get("supersession_reason").unwrap_or(&Value::Null)),
    });

    json!({
        "turn_id": turn_id,
        "user_id": user_id,
        "session_id": session_id,
        "status": status,
        "mode": mode,
        "orchestration_id": opt_str(turn.get("orchestration_id").unwrap_or(&Value::Null)),
        "started_at": started_at,
        "ended_at": ended_at,
        "continued_from_turn_id": opt_str(turn.get("continued_from_turn_id").unwrap_or(&Value::Null)),
        "continued_from_trace_id": opt_str(turn.get("continued_from_trace_id").unwrap_or(&Value::Null)),
        "superseded_by_turn_id": opt_str(turn.get("superseded_by_turn_id").unwrap_or(&Value::Null)),
        "supersession_reason": opt_str(turn.get("supersession_reason").unwrap_or(&Value::Null)),
        "summary": summary,
        "root": root,
    })
}

fn count_steps_in_children(nodes: &[Value]) -> (i64, i64, i64) {
    let mut active = 0i64;
    let mut completed = 0i64;
    let mut failed = 0i64;
    for node in nodes {
        let kind = node.get("kind").and_then(|v| v.as_str()).unwrap_or("");
        let status = node.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if kind != "root" {
            match status {
                "running" => active += 1,
                "completed" => completed += 1,
                "failed" | "cancelled" => failed += 1,
                _ => active += 1,
            }
        }
        if let Some(children) = node.get("children").and_then(|v| v.as_array()) {
            let (a, c, f) = count_steps_in_children(children);
            active += a;
            completed += c;
            failed += f;
        }
    }
    (active, completed, failed)
}

fn build_headline(mode: &str, status: &str, active: i64, completed: i64) -> String {
    match status {
        "completed" => {
            if completed > 0 {
                format!("Completed {} step{}", completed, if completed != 1 { "s" } else { "" })
            } else {
                "Completed".to_string()
            }
        }
        "failed" => "Failed".to_string(),
        "cancelled" => "Cancelled".to_string(),
        _ => {
            if active > 0 {
                if mode == "orchestration" {
                    format!("Running {} step{}", active, if active != 1 { "s" } else { "" })
                } else {
                    "Executing tools".to_string()
                }
            } else {
                "Processing".to_string()
            }
        }
    }
}
