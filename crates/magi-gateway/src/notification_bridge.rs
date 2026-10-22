use crate::ipc::RuntimeConnection;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};
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

#[derive(Deserialize)]
struct NotificationBatch {
    next_id: i64,
    reset: bool,
    events: Vec<NotificationRow>,
}

#[derive(Deserialize)]
struct NotificationRow {
    notification_id: i64,
    channel: String,
    user_id: String,
    session_id: String,
    turn_id: Option<String>,
    data: Option<serde_json::Value>,
}

/// Map persisted channel names to transport-independent product event names.
fn event_name_for_channel(channel: &str) -> String {
    match channel {
        "execution_control" => "turn_execution_control".to_string(),
        "trace_update" => "execution_trace_update".to_string(),
        other => other.to_string(),
    }
}

pub async fn run_notification_bridge(
    connection: Arc<RuntimeConnection>,
    event_emitter: Option<EventEmitFn>,
    storage_ready: Arc<AtomicBool>,
    mut shutdown: watch::Receiver<bool>,
) {
    let mut generation = connection.generation();
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
        if !storage_ready.load(Ordering::Acquire) {
            // The worker owns the complete data audit. Native background readers
            // must honor the same readiness boundary as business HTTP routes.
            last_id = None;
            continue;
        }
        let Some(_permit) = crate::database_gate::global().enter() else {
            last_id = None;
            continue;
        };
        let current_generation = connection.generation();
        if generation != current_generation {
            last_id = None;
            generation = current_generation;
        }
        let response = tokio::select! {
            response = connection.request_with_timeout("runtime.notifications",
                Some(serde_json::json!({"after_id":last_id})), Duration::from_secs(3)) => response,
            _ = shutdown.changed() => return,
        };
        if !storage_ready.load(Ordering::Acquire) || generation != connection.generation() {
            last_id = None;
            continue;
        }
        let Ok(batch) = response.and_then(|value| {
            serde_json::from_value::<NotificationBatch>(value).map_err(|_| {
                crate::ipc::protocol::IpcError {
                    code: -1,
                    message: "Invalid notification feed response".into(),
                }
            })
        }) else {
            continue;
        };
        if !valid_batch(&batch, last_id) {
            last_id = None;
            continue;
        }
        let NotificationBatch {
            next_id,
            events: notifications,
            reset,
        } = batch;
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
            let Some(data) = row.data.filter(|value| value.is_object()) else {
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
            let event = event_name_for_channel(&row.channel);
            let payload = NotificationPayload {
                channel: row.channel,
                user_id: row.user_id.clone(),
                session_id: row.session_id,
                turn_id: row.turn_id,
                data: data.clone(),
            };

            // Emit once to the service event hub.
            if let Some(ref emitter) = event_emitter {
                emitter(&event, &payload);
            }
        }
    }
}

fn valid_batch(batch: &NotificationBatch, after_id: Option<i64>) -> bool {
    if batch.next_id < 0 || batch.events.len() > BATCH_LIMIT as usize {
        return false;
    }
    if batch.reset {
        return batch.events.is_empty();
    }
    let Some(mut previous) = after_id else {
        return false;
    };
    for row in &batch.events {
        if row.notification_id <= previous || row.notification_id > batch.next_id {
            return false;
        }
        previous = row.notification_id;
    }
    previous == batch.next_id
}

#[cfg(test)]
mod frontend_contract_tests {
    use super::*;

    #[test]
    fn feed_cursor_rejects_regressions_and_skipped_pages() {
        let row = |id| NotificationRow {
            notification_id: id,
            channel: "event".into(),
            user_id: "u".into(),
            session_id: "s".into(),
            turn_id: None,
            data: Some(serde_json::json!({})),
        };
        assert!(!valid_batch(
            &NotificationBatch {
                next_id: 3,
                reset: false,
                events: vec![row(2), row(1)]
            },
            Some(0)
        ));
        assert!(!valid_batch(
            &NotificationBatch {
                next_id: 3,
                reset: false,
                events: vec![row(2)]
            },
            Some(0)
        ));
        assert!(!valid_batch(
            &NotificationBatch {
                next_id: 2,
                reset: true,
                events: vec![row(2)]
            },
            None
        ));
        assert!(!valid_batch(
            &NotificationBatch {
                next_id: 1,
                reset: false,
                events: vec![row(1)]
            },
            None
        ));
        assert!(valid_batch(
            &NotificationBatch {
                next_id: 2,
                reset: false,
                events: vec![row(1), row(2)]
            },
            Some(0)
        ));
        assert!(valid_batch(
            &NotificationBatch {
                next_id: 0,
                reset: true,
                events: vec![]
            },
            Some(20)
        ));
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
            "control.ask.requested"
        );
    }
}
