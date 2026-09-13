//! Background facts, never an arbitrary HTTP request or a delayed control command.

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const MAX_BATCH_EVENTS: usize = 32;
pub const MAX_EVENT_BYTES: usize = 64 * 1024;
pub const MAX_BATCH_BYTES: usize = MAX_BATCH_EVENTS * (MAX_EVENT_BYTES + 1024);

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum BackgroundPayload {
    PluginEvent {
        connection_id: String,
        connection_epoch: String,
        plugin_target: String,
        event_type: String,
        data: Value,
    },
    NotificationRead {
        notification_id: i64,
    },
}

impl BackgroundPayload {
    pub fn validate(&self) -> Result<(), String> {
        match self {
            Self::PluginEvent {
                connection_id,
                connection_epoch,
                plugin_target,
                event_type,
                data,
            } => {
                if !valid_key(connection_id)
                    || !valid_id(connection_epoch)
                    || !valid_key(plugin_target)
                    || !valid_key(event_type)
                    || !data.is_object()
                {
                    return Err("Invalid plugin event".into());
                }
            }
            Self::NotificationRead { notification_id }
                if *notification_id <= 0 || *notification_id > 9_007_199_254_740_991 =>
            {
                return Err("Invalid notification identity".into());
            }
            _ => {}
        }
        if serde_json::to_vec(self)
            .map_err(|_| "Invalid background payload")?
            .len()
            > MAX_EVENT_BYTES
        {
            return Err("Background event exceeds size limit".into());
        }
        Ok(())
    }
}

pub fn valid_key(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._:-".contains(&c))
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BackgroundEvent {
    pub event_id: String,
    pub stream: String,
    pub sequence: i64,
    pub occurred_at_ms: i64,
    pub payload: BackgroundPayload,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DeliveryBatch {
    pub server_id: String,
    pub data_epoch: String,
    pub producer_id: String,
    pub events: Vec<BackgroundEvent>,
}

pub fn valid_id(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, c)| {
            if [8, 13, 18, 23].contains(&i) {
                c == b'-'
            } else {
                c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
            }
        })
}

impl DeliveryBatch {
    pub fn validate(&self) -> Result<(), String> {
        if !valid_id(&self.server_id)
            || !valid_id(&self.data_epoch)
            || !valid_id(&self.producer_id)
            || self.events.is_empty()
            || self.events.len() > MAX_BATCH_EVENTS
        {
            return Err("Invalid background batch".into());
        }
        let mut ids = std::collections::HashSet::new();
        let mut streams = std::collections::HashSet::new();
        for event in &self.events {
            if !valid_id(&event.event_id)
                || !valid_key(&event.stream)
                || event.sequence <= 0
                || event.occurred_at_ms < 0
                || !ids.insert(&event.event_id)
                || !streams.insert(&event.stream)
            {
                return Err("Invalid background event identity or ordering".into());
            }
            event.payload.validate()?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum ReceiptStatus {
    Accepted,
    Retry,
    Rejected,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventReceipt {
    pub event_id: String,
    pub status: ReceiptStatus,
    pub code: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DeliveryReceipt {
    pub server_id: String,
    pub data_epoch: String,
    pub receipts: Vec<EventReceipt>,
}
