use crate::db;
use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::watch;

const POLL_INTERVAL: Duration = Duration::from_millis(500);
const BATCH_LIMIT: u32 = 50;

#[derive(Debug, Serialize, Clone)]
pub struct NotificationPayload {
    pub channel: String,
    pub user_id: String,
    pub session_id: String,
    pub turn_id: Option<String>,
    pub data: serde_json::Value,
}

/// Callback type for emitting events to the host runtime (e.g. Tauri events).
/// Receives (event_name, payload). Called once per notification.
pub type EventEmitFn = Arc<dyn Fn(&str, &NotificationPayload) + Send + Sync>;

struct NotificationRow {
    notification_id: i64,
    channel: String,
    user_id: String,
    session_id: String,
    turn_id: Option<String>,
    payload_json: String,
}

fn open_db(db_path: &std::path::Path) -> Option<Connection> {
    Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()
}

fn get_latest_notification_id(conn: &Connection) -> i64 {
    conn.query_row(
        "SELECT COALESCE(MAX(notification_id), 0) FROM runtime_notifications",
        [],
        |row| row.get(0),
    )
    .unwrap_or(0)
}

fn fetch_notifications(conn: &Connection, after_id: i64) -> Vec<NotificationRow> {
    let mut stmt = match conn.prepare(
        "SELECT notification_id, channel, user_id, session_id, turn_id, payload_json
         FROM runtime_notifications
         WHERE notification_id > ?1
         ORDER BY notification_id ASC
         LIMIT ?2",
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };

    let rows = stmt
        .query_map(rusqlite::params![after_id, BATCH_LIMIT], |row| {
            Ok(NotificationRow {
                notification_id: row.get(0)?,
                channel: row.get(1)?,
                user_id: row.get(2)?,
                session_id: row.get(3)?,
                turn_id: row.get(4)?,
                payload_json: row.get(5)?,
            })
        })
        .ok();

    match rows {
        Some(iter) => iter.filter_map(|r| r.ok()).collect(),
        None => Vec::new(),
    }
}

fn parse_payload(json_str: &str) -> serde_json::Value {
    match serde_json::from_str(json_str) {
        Ok(value) => value,
        Err(err) => {
            // Notification bodies may contain conversation text or credentials.
            // Keep only structural diagnostics in the native host log.
            eprintln!(
                "notification_bridge: failed to parse payload_json ({err}); chars={}",
                json_str.chars().count()
            );
            serde_json::Value::Object(serde_json::Map::new())
        }
    }
}

/// Map notification channel to the Tauri event name that matches the frontend's
/// existing event handler expectations.
///
/// Tauri's `listen` rejects event names with `.`, so control-plane channels
/// (which carry dotted names by convention, e.g. ``control.permission.requested``)
/// are translated to colon-separated form for the IPC hop. The frontend bridge
/// is expected to translate them back when constructing the in-app event name.
fn event_name_for_channel(channel: &str) -> String {
    match channel {
        "execution_control" => "turn_execution_control".to_string(),
        "trace_update" => "execution_trace_update".to_string(),
        other if other.starts_with("control.") => other.replace('.', ":"),
        other => other.to_string(),
    }
}

pub async fn run_notification_bridge(
    event_emitter: Option<EventEmitFn>,
    mut shutdown: watch::Receiver<bool>,
) {
    let db_path = db::runtime_trace_db_path();

    // Wait for DB file to exist
    loop {
        if db_path.exists() {
            break;
        }
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_secs(1)) => {}
            _ = shutdown.changed() => { return; }
        }
    }

    let conn = match open_db(&db_path) {
        Some(c) => c,
        None => return,
    };

    let mut last_id = get_latest_notification_id(&conn);

    loop {
        tokio::select! {
            _ = tokio::time::sleep(POLL_INTERVAL) => {}
            _ = shutdown.changed() => { break; }
        }

        if *shutdown.borrow() {
            break;
        }

        let notifications = fetch_notifications(&conn, last_id);
        for row in notifications {
            let mut data = parse_payload(&row.payload_json);
            // Inject top-level fields into data for frontend compatibility
            if let Some(obj) = data.as_object_mut() {
                obj.entry("user_id")
                    .or_insert_with(|| serde_json::Value::String(row.user_id.clone()));
                obj.entry("session_id")
                    .or_insert_with(|| serde_json::Value::String(row.session_id.clone()));
                if let Some(ref turn_id) = row.turn_id {
                    obj.entry("turn_id")
                        .or_insert_with(|| serde_json::Value::String(turn_id.clone()));
                }
            }

            let event = event_name_for_channel(&row.channel);
            let payload = NotificationPayload {
                channel: row.channel,
                user_id: row.user_id.clone(),
                session_id: row.session_id,
                turn_id: row.turn_id,
                data: data.clone(),
            };

            // Emit to host runtime (e.g. Tauri events)
            if let Some(ref emitter) = event_emitter {
                emitter(&event, &payload);
            }

            last_id = row.notification_id;
        }
    }
}
