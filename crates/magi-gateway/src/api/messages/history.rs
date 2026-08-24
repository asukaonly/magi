use axum::extract::Query;
use axum::Json;
use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

use crate::db;

use super::common::DEFAULT_USER_ID;

#[derive(Deserialize)]
pub struct HistoryQuery {
    pub user_id: Option<String>,
    pub session_id: Option<String>,
}

/// Native GET /api/messages/history handler — reads chat.db directly.
pub async fn message_history(Query(params): Query<HistoryQuery>) -> Json<Value> {
    let user_id = params
        .user_id
        .unwrap_or_else(|| DEFAULT_USER_ID.to_string());
    let session_id = match params.session_id {
        Some(sid) if !sid.is_empty() => sid,
        _ => {
            return Json(json!({
                "user_id": user_id,
                "session_id": null,
                "messages": [],
                "count": 0,
                "history_version": 0
            }))
        }
    };

    let result = tokio::task::spawn_blocking(move || query_history(&user_id, &session_id))
        .await
        .unwrap_or_else(|_| {
            json!({
                "user_id": DEFAULT_USER_ID,
                "session_id": null,
                "messages": [],
                "count": 0,
                "history_version": 0
            })
        });
    Json(result)
}

pub(super) fn query_history(user_id: &str, session_id: &str) -> Value {
    let db_path = db::chat_db_path();
    if !db_path.exists() {
        return empty_history(user_id, session_id);
    }
    let conn = match Connection::open_with_flags(&db_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return empty_history(user_id, session_id),
    };

    // Load turns for trace availability lookup
    let turn_ids_with_trace = load_turns_with_trace(user_id, session_id);
    let trace_summaries = load_trace_summaries(user_id, session_id, &turn_ids_with_trace);
    let turn_ux_preferences = load_turn_ux_preferences(&conn, user_id, session_id);
    let history_version = load_history_version(&conn, user_id, session_id);

    // Load messages
    let mut stmt = match conn.prepare(
        "SELECT message_id, session_id, turn_id, user_id, role, message_kind, \
                content_text, payload_json, is_final, is_visible, created_at_ms, \
                sequence_no, replaces_message_id, replaced_by_message_id, persona_id, \
                reply_to_message_id, label_json \
         FROM chat_messages \
         WHERE user_id = ?1 AND session_id = ?2 \
                     AND is_visible = 1 \
                     AND (replaced_by_message_id IS NULL OR message_kind = 'assistant_interim') \
         ORDER BY created_at_ms ASC, sequence_no ASC",
    ) {
        Ok(s) => s,
        Err(_) => return empty_history(user_id, session_id),
    };

    // Collect all rows first for reply-to resolution
    struct MsgRow {
        message_id: String,
        turn_id: Option<String>,
        role: String,
        message_kind: String,
        content_text: String,
        payload_json: String,
        created_at_ms: i64,
        persona_id: Option<String>,
        reply_to_message_id: Option<String>,
        label_json: Option<String>,
    }

    let rows: Vec<MsgRow> = stmt
        .query_map(rusqlite::params![user_id, session_id], |row| {
            Ok(MsgRow {
                message_id: row.get::<_, String>(0)?,
                turn_id: row.get::<_, Option<String>>(2)?,
                role: row.get::<_, String>(4)?,
                message_kind: row.get::<_, String>(5)?,
                content_text: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                payload_json: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                created_at_ms: row.get::<_, i64>(10)?,
                persona_id: row.get::<_, Option<String>>(14)?,
                reply_to_message_id: row.get::<_, Option<String>>(15)?,
                label_json: row.get::<_, Option<String>>(16)?,
            })
        })
        .ok()
        .map(|iter| iter.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();

    // Build message_id → basic info map for reply-to resolution
    let msg_by_id: std::collections::HashMap<&str, (&str, &str, &str)> = rows
        .iter()
        .map(|r| {
            (
                r.message_id.as_str(),
                (
                    r.role.as_str(),
                    r.message_kind.as_str(),
                    r.content_text.as_str(),
                ),
            )
        })
        .collect();

    let messages: Vec<Value> = rows
        .iter()
        .filter_map(|row| {
            let content = row.content_text.trim();
            let payload: Value = serde_json::from_str(&row.payload_json).unwrap_or(json!({}));
            let attachments = payload
                .get("attachments")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();

            if content.is_empty() && attachments.is_empty() {
                return None;
            }

            let kind = display_kind_for_message(row.message_kind.as_str())?;
            let role = if row.message_kind == "user_text" {
                "user"
            } else {
                row.role.as_str()
            };

            let turn_id = row.turn_id.as_deref().filter(|s| !s.is_empty());
            let trace_available = turn_id
                .map(|tid| turn_ids_with_trace.contains(tid))
                .unwrap_or(false);

            let label = parse_label(&row.label_json);

            // Resolve reply_to
            let reply_to = row.reply_to_message_id.as_deref().and_then(|rid| {
                let rid = rid.trim();
                if rid.is_empty() {
                    return None;
                }
                msg_by_id.get(rid).map(|(r_role, r_kind, r_content)| {
                    let excerpt: String = r_content.chars().take(160).collect();
                    json!({
                        "message_id": rid,
                        "role": r_role,
                        "message_kind": if r_kind.is_empty() { Value::Null } else { json!(r_kind) },
                        "content_excerpt": excerpt
                    })
                })
            });

            let mut msg = json!({
                "role": role,
                "kind": kind,
                "content": content,
                "timestamp": row.created_at_ms,
                "message_id": row.message_id,
                "message_kind": row.message_kind,
                "persona_id": row.persona_id,
                "turn_id": turn_id,
                "trace_available": trace_available && kind == "assistant",
            });

            if !payload_is_empty(&payload) {
                msg["payload"] = payload.clone();
            }
            if let Some(tid) = turn_id {
                if let Some(prefs) = turn_ux_preferences.get(tid) {
                    if let Some(mode) = prefs.get("trace_display_mode").and_then(|v| v.as_str()) {
                        if !mode.is_empty() {
                            msg["trace_display_mode"] = json!(mode);
                        }
                    }
                    if let Some(allow) = prefs.get("allow_trace_collapse").and_then(|v| v.as_bool())
                    {
                        msg["allow_trace_collapse"] = json!(allow);
                    }
                }
                if kind == "assistant" {
                    if let Some(summary) = trace_summaries.get(tid) {
                        msg["trace_summary"] = summary.clone();
                        msg["trace_available"] = json!(summary
                            .get("trace_available")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(trace_available));
                    }
                }
            }

            if !attachments.is_empty() {
                msg["attachments"] = json!(attachments);
            }
            if let Some(reply) = reply_to {
                msg["reply_to"] = reply;
            }
            if let Some(lbl) = label {
                msg["label"] = lbl;
            }

            Some(msg)
        })
        .collect();

    let count = messages.len();
    json!({
        "user_id": user_id,
        "session_id": session_id,
        "messages": messages,
        "count": count,
        "history_version": history_version
    })
}

fn load_history_version(conn: &Connection, user_id: &str, session_id: &str) -> i64 {
    conn.query_row(
        "SELECT history_version FROM chat_sessions WHERE user_id = ?1 AND session_id = ?2",
        rusqlite::params![user_id, session_id],
        |row| row.get::<_, i64>(0),
    )
    .unwrap_or(0)
}

/// Load turn_ids that have trace data in runtime_trace.db.
fn load_turns_with_trace(user_id: &str, session_id: &str) -> HashSet<String> {
    let trace_path = db::runtime_trace_db_path();
    if !trace_path.exists() {
        return HashSet::new();
    }
    let conn = match Connection::open_with_flags(&trace_path, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(c) => c,
        Err(_) => return HashSet::new(),
    };
    let mut stmt = match conn.prepare(
        "SELECT DISTINCT turn_id FROM trace_turns \
         WHERE user_id = ?1 AND session_id = ?2",
    ) {
        Ok(s) => s,
        Err(_) => return std::collections::HashSet::new(),
    };
    stmt.query_map(rusqlite::params![user_id, session_id], |row| {
        row.get::<_, String>(0)
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn load_trace_summaries(
    user_id: &str,
    session_id: &str,
    turn_ids: &HashSet<String>,
) -> HashMap<String, Value> {
    turn_ids
        .iter()
        .filter_map(|turn_id| {
            let snapshot = super::super::trace::build_trace_snapshot(user_id, session_id, turn_id);
            let summary = snapshot
                .get("trace")
                .and_then(|trace| trace.get("summary"))
                .cloned()?;
            Some((turn_id.clone(), summary))
        })
        .collect()
}

fn load_turn_ux_preferences(
    conn: &Connection,
    user_id: &str,
    session_id: &str,
) -> HashMap<String, Value> {
    let mut stmt = match conn.prepare(
        "SELECT turn_id, ux_plan_json FROM chat_turns \
         WHERE user_id = ?1 AND session_id = ?2",
    ) {
        Ok(s) => s,
        Err(_) => return HashMap::new(),
    };
    stmt.query_map(rusqlite::params![user_id, session_id], |row| {
        let turn_id: String = row.get(0)?;
        let raw: Option<String> = row.get(1)?;
        let parsed = raw
            .as_deref()
            .and_then(|value| serde_json::from_str::<Value>(value).ok())
            .unwrap_or_else(|| json!({}));
        Ok((turn_id, parsed))
    })
    .ok()
    .map(|iter| iter.filter_map(|r| r.ok()).collect())
    .unwrap_or_default()
}

fn payload_is_empty(payload: &Value) -> bool {
    match payload {
        Value::Null => true,
        Value::Object(map) => map.is_empty(),
        _ => false,
    }
}

fn display_kind_for_message(message_kind: &str) -> Option<&'static str> {
    match message_kind {
        "user_text" => Some("user"),
        "assistant_final"
        | "assistant_interim"
        | "assistant_reaction"
        | "assistant_rhythm_segment" => Some("assistant"),
        "plan_state"
        | "permission_request"
        | "ask_request"
        | "background_task_completion"
        | "status_note"
        | "system_notice" => Some("status"),
        _ => None,
    }
}

fn parse_label(raw: &Option<String>) -> Option<Value> {
    let raw = raw.as_ref()?;
    let parsed: Value = serde_json::from_str(raw).ok()?;
    let obj = parsed.as_object()?;
    let kind = obj.get("kind")?.as_str().filter(|s| !s.is_empty())?;
    let text = obj.get("text")?.as_str().filter(|s| !s.is_empty())?;
    let applied_by = obj.get("applied_by")?.as_str().filter(|s| !s.is_empty())?;
    let source = obj.get("source")?.as_str().filter(|s| !s.is_empty())?;
    let created_at_ms = obj.get("created_at_ms")?.as_i64().filter(|&v| v > 0)?;
    Some(json!({
        "kind": kind,
        "text": text,
        "applied_by": applied_by,
        "source": source,
        "created_at_ms": created_at_ms
    }))
}

#[cfg(test)]
mod tests {
    use super::display_kind_for_message;

    #[test]
    fn rhythm_segments_are_displayed_as_assistant_messages() {
        assert_eq!(
            display_kind_for_message("assistant_rhythm_segment"),
            Some("assistant")
        );
    }
}

fn empty_history(user_id: &str, session_id: &str) -> Value {
    json!({
        "user_id": user_id,
        "session_id": session_id,
        "messages": [],
        "count": 0,
        "history_version": 0
    })
}
