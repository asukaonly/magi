//! Project runtime notifications onto the product protocol before publication.

use serde_json::{json, Map, Value};

use crate::notification_bridge::NotificationPayload;

/// Unknown runtime channels and diagnostic details never become product events.
pub fn project(name: &str, payload: &NotificationPayload) -> Option<(String, Value)> {
    let fields: &[&str] = match name {
        "chat_message_upserted" => &["user_id", "session_id", "message_id", "message", "session_summary"],
        "chat_message_hidden" => &["user_id", "session_id", "message_id", "session_summary"],
        "turn_ux_plan" => &["user_id", "session_id", "turn_id", "ux_plan", "message_id", "message_kind", "timestamp"],
        "turn_execution_control" => &["user_id", "session_id", "turn_id", "run_id", "state", "can_cancel", "label", "timestamp"],
        "context_usage" => &["user_id", "session_id", "turn_id", "used_tokens", "window_size", "input_capacity", "threshold", "measurement", "model_provider", "model_id", "updated_at_ms", "timestamp"],
        "agent_response" => &["user_id", "session_id", "turn_id", "message_id", "message_kind", "content", "is_final", "timestamp", "attachments", "persona_id", "message_payload", "reply_to_message_id", "ux_plan", "trace_available"],
        "agent_response_chunk" => &["user_id", "session_id", "turn_id", "is_final", "seq", "timestamp", "persona_id"],
        "user_notification_added" => &["unread_count"],
        "control.ask.requested" | "control.ask.answered" | "control.permission.requested"
        | "control.permission.resolved" | "control.plan.updated"
        | "control.background.suspended" | "control.background.resumed" => &["session_id", "user_id", "request_id", "run_id"],
        "background_task_state_changed" => return Some(("state.changed".into(), json!({"resource":"background-tasks"}))),
        "code_agent_delegation_event" | "code_agent_delegation_state" => return Some(("state.changed".into(), json!({"resource":"messages"}))),
        _ => return None,
    };
    let source = payload.data.as_object()?;
    let mut data = Map::new();
    for field in fields {
        if let Some(value) = source.get(*field) {
            data.insert((*field).into(), value.clone());
        }
    }
    if name.starts_with("control.") {
        data.insert("session_id".into(), Value::String(payload.session_id.clone()));
    }
    if name == "agent_response_chunk" {
        let event = source.get("event")?.as_object()?;
        let kind = event.get("kind")?.as_str()?;
        if !matches!(kind, "text_delta" | "text_flush" | "text_reset" | "status_update" | "error" | "done") {
            return None;
        }
        let preview: Map<String, Value> = ["kind", "text", "error_kind", "error_message", "step_label"]
            .into_iter().filter_map(|key| event.get(key).map(|value| (key.into(), value.clone()))).collect();
        data.insert("event".into(), Value::Object(preview));
    }
    Some((name.into(), Value::Object(data)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn payload(data: Value) -> NotificationPayload {
        NotificationPayload { channel: "internal".into(), user_id: "local_user".into(),
            session_id: "s".into(), turn_id: Some("t".into()), data }
    }

    #[test]
    fn product_projection_excludes_runtime_channels_and_tool_arguments() {
        assert!(project("new_internal_channel", &payload(json!({"secret":1}))).is_none());
        assert!(project("execution_trace_update", &payload(json!({"trace":1}))).is_none());
        assert!(project("agent_response_chunk", &payload(json!({"event":{"kind":"tool_call_args","text":"secret"}}))).is_none());
        let (_, preview) = project("agent_response_chunk", &payload(json!({
            "session_id":"s", "event":{"kind":"text_delta","text":"Hello","tool_arguments":{"secret":1}}, "internal":1
        }))).unwrap();
        assert_eq!(preview, json!({"session_id":"s","event":{"kind":"text_delta","text":"Hello"}}));
        let (_, question) = project("control.ask.requested", &payload(json!({"request_id":"q","tool_arguments":{"secret":1}}))).unwrap();
        assert_eq!(question, json!({"session_id":"s","request_id":"q"}));
    }
}
