use crate::db;
use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::watch;

const POLL_INTERVAL: Duration = Duration::from_millis(500);
const BATCH_LIMIT: u32 = 200;

#[derive(Debug, Serialize, Clone)]
pub struct NotificationPayload {
    pub channel: String,
    pub user_id: String,
    pub session_id: String,
    pub turn_id: Option<String>,
    pub data: serde_json::Value,
}

/// Callback for transport-independent notification delivery.
/// Receives (event_name, payload). Called once per notification.
pub type EventEmitFn = Arc<dyn Fn(&str, &NotificationPayload) + Send + Sync>;

struct NotificationRow {
    notification_id: i64,
    channel: String,
    user_id: String,
    session_id: String,
    turn_id: Option<String>,
    payload_json: Option<String>,
}

fn open_db(db_path: &std::path::Path) -> Option<Connection> {
    Connection::open_with_flags(
        db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()
}

fn read_batch(
    db_path: &std::path::Path,
    after_id: Option<i64>,
) -> Result<(i64, Vec<NotificationRow>, bool), String> {
    let _permit = crate::database_gate::global()
        .enter()
        .ok_or("Center maintenance is active")?;
    let conn = open_db(db_path).ok_or("Notification store is unavailable")?;
    conn.busy_timeout(Duration::from_millis(100))
        .map_err(|e| e.to_string())?;
    let latest: i64 = conn
        .query_row(
            "SELECT COALESCE(MAX(notification_id), 0) FROM runtime_notifications",
            [],
            |row| row.get(0),
        )
        .map_err(|e| e.to_string())?;
    let Some(after_id) = after_id.filter(|id| *id <= latest) else {
        return Ok((latest, vec![], true));
    };
    let mut statement = conn.prepare(
        "SELECT notification_id, channel, user_id, session_id, turn_id,
         CASE WHEN length(CAST(payload_json AS BLOB)) <= 65536 THEN payload_json ELSE NULL END
         FROM runtime_notifications WHERE notification_id > ?1 ORDER BY notification_id ASC LIMIT ?2"
    ).map_err(|e| e.to_string())?;
    let rows = statement
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
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    let next_id = rows
        .last()
        .map(|row| row.notification_id)
        .unwrap_or(after_id);
    Ok((next_id, rows, false))
}

fn parse_payload(json_str: &str) -> Option<serde_json::Value> {
    match serde_json::from_str(json_str) {
        Ok(value) => Some(value),
        Err(err) => {
            // Notification bodies may contain conversation text or credentials.
            // Keep only structural diagnostics in the native host log.
            eprintln!(
                "notification_bridge: failed to parse payload_json ({err}); chars={}",
                json_str.chars().count()
            );
            None
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
    let mut last_id = None;
    let mut interval = POLL_INTERVAL;
    loop {
        tokio::select! {
            _ = tokio::time::sleep(interval) => {},
            _ = shutdown.changed() => return,
        }
        if *shutdown.borrow() {
            return;
        }
        let path = db_path.clone();
        // One bounded read task serves every subscriber. No SQLite handle survives a restore.
        let Ok(Ok((next_id, notifications, reset))) =
            tokio::task::spawn_blocking(move || read_batch(&path, last_id)).await
        else {
            continue;
        };
        interval = if notifications.len() == BATCH_LIMIT as usize {
            Duration::from_millis(5)
        } else {
            POLL_INTERVAL
        };
        last_id = Some(next_id);
        if reset {
            if let Some(ref emitter) = event_emitter {
                emitter(
                    "server_resync_required",
                    &NotificationPayload {
                        channel: "server_resync_required".into(),
                        user_id: String::new(),
                        session_id: String::new(),
                        turn_id: None,
                        data: serde_json::json!({"reason":"notification_source_changed"}),
                    },
                );
            }
        }
        for row in notifications {
            let Some(mut data) = row.payload_json.as_deref().and_then(parse_payload) else {
                if let Some(ref emitter) = event_emitter {
                    emitter(
                        "server_resync_required",
                        &NotificationPayload {
                            channel: "server_resync_required".into(),
                            user_id: row.user_id,
                            session_id: row.session_id,
                            turn_id: row.turn_id,
                            data: serde_json::json!({"reason":"notification_snapshot_required"}),
                        },
                    );
                }
                continue;
            };
            // Preserve authoritative routing fields in the domain event payload.
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
        }
    }
}

#[cfg(test)]
mod frontend_contract_tests {
    use super::*;

    #[test]
    fn reader_bounds_rows_and_detects_store_rewind() {
        let path = std::env::temp_dir().join(format!("magi-events-{}.db", uuid::Uuid::new_v4()));
        let conn = Connection::open(&path).unwrap();
        conn.execute_batch(
            "CREATE TABLE runtime_notifications (notification_id INTEGER PRIMARY KEY,
            channel TEXT, user_id TEXT, session_id TEXT, turn_id TEXT, payload_json TEXT)",
        )
        .unwrap();
        assert_eq!(read_batch(&path, None).unwrap().0, 0);
        for id in 1..=201 {
            conn.execute("INSERT INTO runtime_notifications VALUES (?1, 'chat_message_upserted', 'user', 'session', NULL, ?2)",
                rusqlite::params![id, if id == 1 { "x".repeat(70_000) } else { "{}".into() }]).unwrap();
        }
        let (next, rows, reset) = read_batch(&path, Some(0)).unwrap();
        assert_eq!(next, 200);
        assert_eq!(rows.len(), 200);
        assert!(rows[0].payload_json.is_none());
        assert!(!reset);
        assert_eq!(read_batch(&path, Some(next)).unwrap().1.len(), 1);
        conn.execute("DELETE FROM runtime_notifications", [])
            .unwrap();
        assert!(read_batch(&path, Some(next)).unwrap().2);
        drop(conn);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn native_notification_matches_frontend_fixture() {
        let input: serde_json::Value = serde_json::from_str(include_str!(
            "../../../contracts/api/frontend-events-examples.json"
        ))
        .unwrap();
        let payload = NotificationPayload {
            channel: "chat_message_upserted".to_string(),
            user_id: "fixture-user".to_string(),
            session_id: "fixture-session".to_string(),
            turn_id: None,
            data: input["upsert"].clone(),
        };
        let serialized = serde_json::to_value(payload).unwrap();
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../contracts/api/frontend-native-notification.json");
        if std::env::var("UPDATE_FRONTEND_NATIVE_CONTRACTS").as_deref() == Ok("1") {
            std::fs::write(
                &path,
                format!("{}\n", serde_json::to_string_pretty(&serialized).unwrap()),
            )
            .unwrap();
        }
        let expected: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        assert_eq!(serialized, expected);
        assert_eq!(
            event_name_for_channel("execution_control"),
            "turn_execution_control"
        );
        assert_eq!(
            event_name_for_channel("control.ask.requested"),
            "control:ask:requested"
        );
    }
}
