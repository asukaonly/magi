use serde_json::{json, Value};
use std::collections::HashMap;

pub(super) fn ms_to_seconds(val: &Value) -> Option<f64> {
    val.as_i64().map(|ms| ms as f64 / 1000.0)
}

pub(super) fn opt_str(val: &Value) -> Option<&str> {
    val.as_str().filter(|s| !s.is_empty())
}

fn safe_int(val: &Value, default: i64) -> i64 {
    val.as_i64().unwrap_or(default)
}

pub(super) fn normalize_status(raw: &str) -> &str {
    match raw {
        "ok" | "success" | "succeeded" | "done" => "completed",
        "error" | "errored" | "timeout" | "timed_out" => "failed",
        "" => "running",
        other => other,
    }
}

pub(super) fn is_terminal(status: &str) -> bool {
    matches!(status, "completed" | "failed" | "cancelled" | "skipped")
}

fn map_trace_kind(node_type: &str) -> &str {
    match node_type {
        "turn" => "root",
        "intent_resolution" | "intent" => "intent",
        "orchestration_plan" | "plan" => "planning",
        "worker_dispatch" => "dispatch",
        "worker" | "worker_attempt" | "subtask" | "subtask_group" => "worker",
        "tool_call" | "tool_invocation" | "tool" => "tool",
        "llm_call" | "llm" => "llm",
        "iteration" => "iteration",
        "response_emit" => "response",
        "rhythm_processing" => "rhythm",
        _ => "step",
    }
}

fn default_trace_label(node_type: &str) -> &str {
    match node_type {
        "turn" => "Turn",
        "intent_resolution" | "intent" => "Intent resolution",
        "plan" | "orchestration_plan" => "Planning",
        "worker_dispatch" => "Worker dispatch",
        "worker_attempt" => "Worker attempt",
        "tool_call" | "tool_invocation" | "tool" => "Tool call",
        "llm_call" | "llm" => "LLM call",
        "iteration" => "Iteration",
        "response_emit" => "Response",
        "rhythm_processing" => "Response rhythm processing",
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
        let preview = tc
            .get("result_preview")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !preview.is_empty() {
            return preview.to_string();
        }
    }
    if let Some(lc) = llm_call {
        let preview = lc
            .get("response_preview")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .trim();
        if !preview.is_empty() {
            return preview.to_string();
        }
    }
    String::new()
}

pub(super) fn build_trace_node(
    span: &HashMap<String, Value>,
    llm_call: Option<&HashMap<String, Value>>,
    tool_call: Option<&HashMap<String, Value>>,
    intent_resolution: Option<&HashMap<String, Value>>,
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
    if let Some(input_preview) = span
        .get("input_preview")
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty())
    {
        metadata["input"] = json!({ "preview": input_preview.trim() });
    }
    if let Some(output_preview) = span
        .get("output_preview")
        .and_then(|v| v.as_str())
        .filter(|s| !s.trim().is_empty())
    {
        metadata["output"] = json!({ "preview": output_preview.trim() });
    }

    if let Some(lc) = llm_call {
        metadata["provider"] = lc.get("provider").cloned().unwrap_or(Value::Null);
        metadata["model"] = lc.get("model").cloned().unwrap_or(Value::Null);
        metadata["input_tokens"] =
            json!(safe_int(lc.get("input_tokens").unwrap_or(&Value::Null), 0));
        metadata["output_tokens"] =
            json!(safe_int(lc.get("output_tokens").unwrap_or(&Value::Null), 0));
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
        metadata["thinking_enabled"] = json!(
            lc.get("thinking_enabled")
                .and_then(|v| v.as_i64())
                .unwrap_or(0)
                != 0
        );
        if let Some(request_preview) = lc
            .get("request_preview")
            .and_then(|v| v.as_str())
            .filter(|s| !s.trim().is_empty())
        {
            metadata["request_preview"] = json!(request_preview.trim());
            metadata["input"] = json!({ "preview": request_preview.trim() });
        }
        if let Some(response_preview) = lc
            .get("response_preview")
            .and_then(|v| v.as_str())
            .filter(|s| !s.trim().is_empty())
        {
            metadata["response_preview"] = json!(response_preview.trim());
            metadata["output"] = json!({ "preview": response_preview.trim() });
        }
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

    if let Some(ir) = intent_resolution {
        let selected_payload = ir
            .get("selected_tools_json")
            .and_then(|v| v.as_str())
            .and_then(|s| serde_json::from_str::<Value>(s).ok())
            .unwrap_or(Value::Null);
        metadata["intent_label"] = ir.get("intent").cloned().unwrap_or(Value::Null);
        metadata["execution_mode"] = ir.get("execution_mode").cloned().unwrap_or(Value::Null);
        metadata["route_reason"] = ir.get("route_reason").cloned().unwrap_or(Value::Null);
        metadata["selected_worker_type"] = ir
            .get("selected_worker_type")
            .cloned()
            .unwrap_or(Value::Null);
        if selected_payload.is_array() {
            metadata["selected_tools"] = selected_payload.clone();
        } else if selected_payload.is_object() {
            metadata["selected_tools"] = selected_payload
                .get("selected_tools")
                .cloned()
                .unwrap_or(Value::Null);
            metadata["router_tools"] = selected_payload
                .get("router_tools")
                .cloned()
                .unwrap_or(Value::Null);
            metadata["task_hint"] = selected_payload
                .get("task_hint")
                .cloned()
                .unwrap_or(Value::Null);
            metadata["recommended_tools"] = selected_payload
                .get("recommended_tools")
                .cloned()
                .unwrap_or(Value::Null);
            if let Some(llm_trace) = selected_payload
                .get("llm_trace")
                .and_then(|v| v.as_object())
            {
                metadata["provider"] = llm_trace.get("provider").cloned().unwrap_or(Value::Null);
                metadata["model"] = llm_trace.get("model").cloned().unwrap_or(Value::Null);
                metadata["input_tokens"] = json!(safe_int(
                    llm_trace.get("input_tokens").unwrap_or(&Value::Null),
                    0
                ));
                metadata["output_tokens"] = json!(safe_int(
                    llm_trace.get("output_tokens").unwrap_or(&Value::Null),
                    0
                ));
                metadata["total_tokens"] = json!(safe_int(
                    llm_trace.get("total_tokens").unwrap_or(&Value::Null),
                    0
                ));
                metadata["duration_ms"] = json!(safe_int(
                    llm_trace.get("duration_ms").unwrap_or(&Value::Null),
                    safe_int(span.get("duration_ms").unwrap_or(&Value::Null), 0)
                ));
                metadata["thinking_enabled"] = json!(llm_trace
                    .get("thinking_enabled")
                    .and_then(|v| v.as_bool())
                    .unwrap_or(false));
                if let Some(request_preview) = llm_trace
                    .get("request_preview")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.trim().is_empty())
                {
                    metadata["request_preview"] = json!(request_preview.trim());
                    metadata["input"] = json!({ "preview": request_preview.trim() });
                }
                if let Some(response_preview) = llm_trace
                    .get("response_preview")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.trim().is_empty())
                {
                    metadata["response_preview"] = json!(response_preview.trim());
                    metadata["output"] = json!({ "preview": response_preview.trim() });
                }
            }
        }
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

pub(super) fn count_steps_in_children(nodes: &[Value]) -> (i64, i64, i64) {
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
            let (nested_active, nested_completed, nested_failed) =
                count_steps_in_children(children);
            active += nested_active;
            completed += nested_completed;
            failed += nested_failed;
        }
    }
    (active, completed, failed)
}

pub(super) fn build_headline(mode: &str, status: &str, active: i64, completed: i64) -> String {
    match status {
        "completed" => {
            if completed > 0 {
                format!(
                    "Completed {} step{}",
                    completed,
                    if completed != 1 { "s" } else { "" }
                )
            } else {
                "Completed".to_string()
            }
        }
        "failed" => "Failed".to_string(),
        "cancelled" => "Cancelled".to_string(),
        _ => {
            if active > 0 {
                if mode == "orchestration" {
                    format!(
                        "Running {} step{}",
                        active,
                        if active != 1 { "s" } else { "" }
                    )
                } else {
                    "Executing tools".to_string()
                }
            } else {
                "Processing".to_string()
            }
        }
    }
}
