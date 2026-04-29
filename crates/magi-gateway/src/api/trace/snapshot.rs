use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::db;

use super::nodes::{
    build_headline, build_trace_node, count_steps_in_children, is_terminal, ms_to_seconds,
    normalize_status, opt_str,
};
use super::rows::{load_detail_rows, load_trace_spans, load_trace_turn};

pub(in crate::api) fn build_trace_snapshot(
    user_id: &str,
    session_id: &str,
    turn_id: &str,
) -> Value {
    let trace_path = db::runtime_trace_db_path();
    if !trace_path.exists() {
        return json!({"success": false, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null});
    }
    let conn = match Connection::open_with_flags(&trace_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => {
            return json!({"success": false, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null})
        }
    };

    let turn = match load_trace_turn(&conn, user_id, session_id, turn_id) {
        Some(t) => t,
        None => {
            return json!({"success": true, "user_id": user_id, "session_id": session_id, "turn_id": turn_id, "trace": null})
        }
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

fn assemble_snapshot(
    user_id: &str,
    session_id: &str,
    turn: &HashMap<String, Value>,
    spans: &[HashMap<String, Value>],
    llm_calls: &[HashMap<String, Value>],
    tool_calls: &[HashMap<String, Value>],
) -> Value {
    let turn_id = turn.get("turn_id").and_then(|v| v.as_str()).unwrap_or("");
    let trace_id = turn.get("trace_id").and_then(|v| v.as_str()).unwrap_or("");
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
        let node = build_trace_node(
            span,
            llm_by_span.get(span_id.as_str()).copied(),
            tool_by_span.get(span_id.as_str()).copied(),
        );
        node_by_id.insert(span_id.clone(), node);

        let parent = span
            .get("parent_span_id")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string());
        children_by_parent.entry(parent).or_default().push(span_id);
    }

    for (parent_id, child_ids) in &children_by_parent {
        if let Some(pid) = parent_id {
            let mut sorted_children: Vec<Value> = child_ids
                .iter()
                .filter_map(|cid| node_by_id.remove(cid))
                .collect();
            sorted_children.sort_by(|a, b| {
                let a_started = a.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let b_started = b.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
                a_started
                    .partial_cmp(&b_started)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            if let Some(parent) = node_by_id.get_mut(pid) {
                if let Some(arr) = parent.get_mut("children").and_then(|v| v.as_array_mut()) {
                    arr.extend(sorted_children);
                }
            } else {
                for child in sorted_children {
                    let child_id = child
                        .get("id")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_string();
                    if !child_id.is_empty() {
                        node_by_id.insert(child_id, child);
                    }
                }
            }
        }
    }

    let turn_span_id = format!("{}:turn", turn_id);
    let mut top_ids: Vec<String> = children_by_parent.get(&None).cloned().unwrap_or_default();
    let turn_node = node_by_id.remove(&turn_span_id);
    if turn_node.is_none() {
        if let Some(turn_children) = children_by_parent.get(&Some(turn_span_id.clone())) {
            top_ids.extend(turn_children.clone());
        }
    }
    top_ids.retain(|id| id != &turn_span_id);

    let mut top_level: Vec<Value> = top_ids
        .iter()
        .filter_map(|id| node_by_id.remove(id))
        .collect();
    if let Some(tn) = &turn_node {
        if let Some(arr) = tn.get("children").and_then(|v| v.as_array()) {
            top_level.extend(arr.clone());
        }
    }
    top_level.sort_by(|a, b| {
        let a_started = a.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let b_started = b.get("started_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
        a_started
            .partial_cmp(&b_started)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    let (active, completed, failed) = count_steps_in_children(&top_level);
    let duration = match (started_at, ended_at) {
        (Some(started), Some(ended)) => (ended - started).max(0.0),
        _ => 0.0,
    };

    let trace_available = !top_level.is_empty();
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
        "trace_available": trace_available,
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
