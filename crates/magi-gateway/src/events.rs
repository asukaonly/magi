//! Bounded, resumable fan-out of hints about authoritative server state.

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use serde::Serialize;
use serde_json::{json, Value};
use tokio::sync::{broadcast, OwnedSemaphorePermit, Semaphore};

const RETAINED_EVENTS: usize = 256;
const MAX_EVENT_BYTES: usize = 64 * 1024;
const MAX_REPLAY_BYTES: usize = 8 * 1024 * 1024;

#[derive(Clone, Serialize)]
pub struct EventEnvelope {
    pub server_id: String,
    pub epoch: String,
    pub sequence: u64,
    pub event_id: String,
    pub event_type: String,
    pub data: Value,
}

pub struct ServerEvent {
    pub envelope: EventEnvelope,
    pub json: String,
}

struct History {
    epoch: String,
    sequence: u64,
    bytes: usize,
    events: VecDeque<Arc<ServerEvent>>,
}

pub struct EventHub {
    server_id: String,
    history: Mutex<History>,
    sender: broadcast::Sender<Arc<ServerEvent>>,
    slots: Arc<Semaphore>,
}

pub struct Subscription {
    pub replay: VecDeque<Arc<ServerEvent>>,
    pub receiver: broadcast::Receiver<Arc<ServerEvent>>,
    _slot: OwnedSemaphorePermit,
}

impl EventHub {
    pub fn new(server_id: String) -> Self {
        Self {
            server_id,
            history: Mutex::new(History {
                epoch: uuid::Uuid::new_v4().to_string(),
                sequence: 0,
                bytes: 0,
                events: VecDeque::new(),
            }),
            sender: broadcast::channel(RETAINED_EVENTS).0,
            slots: Arc::new(Semaphore::new(64)),
        }
    }

    pub fn publish(&self, event_type: &str, data: Value) {
        let mut history = self.history.lock().unwrap_or_else(|e| e.into_inner());
        history.sequence += 1;
        let mut event = self.event(&history, event_type, data);
        if event.json.len() > MAX_EVENT_BYTES {
            event = self.event(
                &history,
                "resync_required",
                json!({"reason":"event_too_large"}),
            );
        }
        let event = Arc::new(event);
        history.bytes += event.json.len();
        history.events.push_back(Arc::clone(&event));
        while history.events.len() > RETAINED_EVENTS || history.bytes > MAX_REPLAY_BYTES {
            if let Some(oldest) = history.events.pop_front() {
                history.bytes -= oldest.json.len();
            }
        }
        // Subscription and publication share this lock, eliminating the replay/live gap.
        let _ = self.sender.send(event);
    }

    pub fn reset(&self, reason: &str) {
        let mut history = self.history.lock().unwrap_or_else(|e| e.into_inner());
        history.epoch = uuid::Uuid::new_v4().to_string();
        history.sequence = 0;
        history.bytes = 0;
        history.events.clear();
        let event = Arc::new(self.event(&history, "resync_required", json!({"reason":reason})));
        let _ = self.sender.send(event);
    }

    pub fn subscribe(&self, after: Option<&str>) -> Option<Subscription> {
        let slot = Arc::clone(&self.slots).try_acquire_owned().ok()?;
        let history = self.history.lock().unwrap_or_else(|e| e.into_inner());
        let receiver = self.sender.subscribe();
        let sequence = after
            .and_then(|id| id.rsplit_once(':'))
            .filter(|(epoch, _)| *epoch == history.epoch)
            .and_then(|(_, sequence)| sequence.parse::<u64>().ok())
            .filter(|sequence| *sequence <= history.sequence)
            .filter(|sequence| {
                history
                    .events
                    .front()
                    .is_none_or(|first| sequence.saturating_add(1) >= first.envelope.sequence)
            });
        let replay = match sequence {
            Some(sequence) => history
                .events
                .iter()
                .filter(|event| event.envelope.sequence > sequence)
                .cloned()
                .collect(),
            None => VecDeque::from([Arc::new(self.event(
                &history,
                "resync_required",
                json!({"reason":"snapshot_required"}),
            ))]),
        };
        Some(Subscription {
            replay,
            receiver,
            _slot: slot,
        })
    }

    pub fn resync_hint(&self, reason: &str) -> Arc<ServerEvent> {
        let history = self.history.lock().unwrap_or_else(|e| e.into_inner());
        Arc::new(self.event(&history, "resync_required", json!({"reason": reason})))
    }

    pub fn status(&self) -> Value {
        let history = self.history.lock().unwrap_or_else(|e| e.into_inner());
        json!({"epoch":history.epoch, "sequence":history.sequence})
    }

    fn event(&self, history: &History, event_type: &str, data: Value) -> ServerEvent {
        let envelope = EventEnvelope {
            server_id: self.server_id.clone(),
            epoch: history.epoch.clone(),
            sequence: history.sequence,
            event_id: format!("{}:{}", history.epoch, history.sequence),
            event_type: event_type.into(),
            data,
        };
        let json = serde_json::to_string(&envelope).expect("serialize event envelope");
        ServerEvent { envelope, json }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn replay_live_transition_has_no_gap_and_clients_are_independent() {
        let hub = EventHub::new("server".into());
        let first = hub.subscribe(None).unwrap().replay.pop_front().unwrap();
        hub.publish("state.changed", json!({"resource":"tasks"}));
        let mut client = hub.subscribe(Some(&first.envelope.event_id)).unwrap();
        assert_eq!(client.replay.pop_front().unwrap().envelope.sequence, 1);
        hub.publish("state.changed", Value::Null);
        assert_eq!(client.receiver.recv().await.unwrap().envelope.sequence, 2);
        let mut slow = hub.subscribe(None).unwrap();
        for _ in 0..RETAINED_EVENTS + 1 {
            hub.publish("state.changed", Value::Null);
        }
        assert!(matches!(
            slow.receiver.recv().await,
            Err(broadcast::error::RecvError::Lagged(_))
        ));
        let resync = hub
            .subscribe(Some(&first.envelope.event_id))
            .unwrap()
            .replay
            .pop_front()
            .unwrap();
        assert_eq!(resync.envelope.event_type, "resync_required");
        hub.reset("restore");
        let reset = hub
            .subscribe(Some(&resync.envelope.event_id))
            .unwrap()
            .replay
            .pop_front()
            .unwrap();
        assert_ne!(reset.envelope.epoch, resync.envelope.epoch);
    }

    #[test]
    fn oversized_payloads_become_bounded_resynchronization_hints() {
        let hub = EventHub::new("server".into());
        let initial = hub.subscribe(None).unwrap().replay.pop_front().unwrap();
        hub.publish(
            "runtime.notification",
            json!({"text":"x".repeat(MAX_EVENT_BYTES * 2)}),
        );
        let replay = hub
            .subscribe(Some(&initial.envelope.event_id))
            .unwrap()
            .replay;
        assert_eq!(replay[0].envelope.event_type, "resync_required");
        assert!(replay[0].json.len() < 1024);
    }
}
