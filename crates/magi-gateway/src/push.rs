//! Optional APNs transport. The durable inbox remains authoritative.

use crate::{api::state::ApiState, auth::push::PushDevice};
use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine,
};
use ring::signature::{EcdsaKeyPair, ECDSA_P256_SHA256_FIXED_SIGNING};
use serde::Deserialize;
use serde_json::json;
use std::{
    sync::Mutex,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

pub struct Apns {
    client: reqwest::Client,
    key: EcdsaKeyPair,
    key_id: String,
    team_id: String,
    topic: String,
    token: Mutex<(u64, String)>,
}

#[derive(Deserialize)]
pub struct PushFeed {
    pub next_id: i64,
    pub items: Vec<PushItem>,
}
#[derive(Deserialize)]
pub struct PushItem {
    pub id: i64,
    pub kind: String,
    pub expires_at: u64,
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

impl Apns {
    pub fn from_env() -> Result<Option<Self>, String> {
        let names = [
            "MAGI_APNS_KEY_FILE",
            "MAGI_APNS_KEY_ID",
            "MAGI_APNS_TEAM_ID",
            "MAGI_APNS_TOPIC",
        ];
        let values: Vec<_> = names
            .iter()
            .map(|n| std::env::var(n).unwrap_or_default())
            .collect();
        if values.iter().all(String::is_empty) {
            return Ok(None);
        }
        if values.iter().any(String::is_empty)
            || values[1..3]
                .iter()
                .any(|v| v.len() != 10 || !v.bytes().all(|b| b.is_ascii_alphanumeric()))
            || values[3].len() > 255
            || !values[3]
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b".-_".contains(&b))
        {
            return Err("Incomplete or invalid APNs configuration".into());
        }
        let pem =
            std::fs::read_to_string(&values[0]).map_err(|_| "Cannot read APNs signing key")?;
        let encoded: String = pem
            .lines()
            .filter(|line| !line.starts_with("-----"))
            .collect();
        let der = STANDARD
            .decode(encoded)
            .map_err(|_| "Invalid APNs signing key")?;
        let key = EcdsaKeyPair::from_pkcs8(
            &ECDSA_P256_SHA256_FIXED_SIGNING,
            &der,
            &ring::rand::SystemRandom::new(),
        )
        .map_err(|_| "Invalid APNs signing key")?;
        let client = reqwest::Client::builder()
            .https_only(true)
            .http2_prior_knowledge()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(10))
            .build()
            .map_err(|_| "Cannot initialize APNs transport")?;
        Ok(Some(Self {
            client,
            key,
            key_id: values[1].clone(),
            team_id: values[2].clone(),
            topic: values[3].clone(),
            token: Mutex::new((0, String::new())),
        }))
    }

    fn authorization(&self) -> Result<String, String> {
        let mut cached = self.token.lock().unwrap_or_else(|e| e.into_inner());
        let issued = now();
        if cached.1.is_empty() || issued.saturating_sub(cached.0) > 3000 {
            let header =
                URL_SAFE_NO_PAD.encode(json!({"alg":"ES256","kid":self.key_id}).to_string());
            let claims =
                URL_SAFE_NO_PAD.encode(json!({"iss":self.team_id,"iat":issued}).to_string());
            let message = format!("{header}.{claims}");
            let signature = self
                .key
                .sign(&ring::rand::SystemRandom::new(), message.as_bytes())
                .map_err(|_| "APNs signing failed")?;
            *cached = (
                issued,
                format!("{message}.{}", URL_SAFE_NO_PAD.encode(signature.as_ref())),
            );
        }
        Ok(cached.1.clone())
    }

    async fn send(&self, device: &PushDevice, item: &PushItem, server: &str) -> Result<bool, ()> {
        let host = if device.environment == "development" {
            "api.sandbox.push.apple.com"
        } else {
            "api.push.apple.com"
        };
        let response = self
            .client
            .post(format!("https://{host}/3/device/{}", device.token))
            .bearer_auth(self.authorization().map_err(|_| ())?)
            .header("apns-topic", &self.topic)
            .header("apns-push-type", "alert")
            .header("apns-priority", "10")
            .header("apns-expiration", item.expires_at.to_string())
            .header("apns-collapse-id", format!("magi-{}", item.id))
            .json(&payload(device, item, server))
            .send()
            .await
            .map_err(|_| ())?;
        let status = response.status();
        if status.is_success() {
            return Ok(false);
        }
        if status.as_u16() == 410 {
            return Ok(true);
        }
        let reason = response
            .json::<serde_json::Value>()
            .await
            .unwrap_or_default();
        if matches!(
            reason["reason"].as_str(),
            Some("BadDeviceToken" | "DeviceTokenNotForTopic" | "Unregistered")
        ) {
            return Ok(true);
        }
        Err(())
    }
}

fn payload(device: &PushDevice, item: &PushItem, server: &str) -> serde_json::Value {
    let key = match item.kind.as_str() {
        "interaction_required" => "push.input",
        "personal_task_reminder" => "push.reminder",
        _ => "push.task",
    };
    json!({"aps":{"alert":{"title":"Magi","loc-key":key},"sound":"default"},
        "magi":{"server_id":server,"data_epoch":device.data_epoch,"notification_id":item.id}})
}

pub async fn feed(state: &ApiState, after: Option<i64>) -> Result<PushFeed, ()> {
    let value = state
        .ipc_client
        .request_with_timeout(
            "notifications.push-feed",
            Some(json!({"after_id":after})),
            Duration::from_secs(3),
        )
        .await
        .map_err(|_| ())?;
    let feed: PushFeed = serde_json::from_value(value).map_err(|_| ())?;
    if feed.next_id < 0
        || feed.items.len() > 100
        || feed.items.iter().any(|i| {
            i.id <= after.unwrap_or(0)
                || i.id > feed.next_id
                || !matches!(
                    i.kind.as_str(),
                    "interaction_required" | "personal_task_reminder" | "background_task_finished"
                )
        })
    {
        return Err(());
    }
    Ok(feed)
}

pub async fn run(state: ApiState, mut shutdown: tokio::sync::watch::Receiver<bool>) {
    let Some(apns) = &state.apns else {
        return;
    };
    let mut delay = 5;
    loop {
        tokio::select! { _=tokio::time::sleep(Duration::from_secs(delay))=>{}, _=shutdown.changed()=>return }
        if *shutdown.borrow() {
            return;
        }
        if !state
            .storage_ready
            .load(std::sync::atomic::Ordering::Acquire)
        {
            continue;
        }
        let Some(_permit) = crate::database_gate::global().enter() else {
            continue;
        };
        let Some(control) = &state.maintenance else {
            continue;
        };
        let epoch = control.status().data_epoch;
        let Ok(devices) = state.security.auth.push_devices() else {
            continue;
        };
        let mut failed = false;
        for mut device in devices {
            if device.data_epoch != epoch {
                continue;
            }
            let Ok(batch) = feed(&state, Some(device.after_id)).await else {
                failed = true;
                continue;
            };
            let mut invalid = false;
            let mut retry = false;
            for item in &batch.items {
                if item.expires_at <= now() {
                    continue;
                }
                if !state
                    .security
                    .auth
                    .push_devices()
                    .unwrap_or_default()
                    .contains(&device)
                {
                    retry = true;
                    break;
                }
                match apns
                    .send(&device, item, &state.security.auth.server_id)
                    .await
                {
                    Ok(retired) => {
                        if state
                            .security
                            .auth
                            .advance_push(&device, item.id, retired)
                            .is_err()
                        {
                            retry = true;
                            break;
                        }
                        device.after_id = item.id;
                        if retired {
                            invalid = true;
                            break;
                        }
                    }
                    Err(()) => {
                        retry = true;
                        break;
                    }
                }
            }
            if !invalid && !retry {
                let _ = state
                    .security
                    .auth
                    .advance_push(&device, batch.next_id, false);
            }
            failed |= retry;
        }
        delay = if failed { (delay * 2).min(300) } else { 5 };
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn payload_is_content_free_and_scoped() {
        let device = PushDevice {
            client_id: "client".into(),
            token: "private".into(),
            environment: "development".into(),
            data_epoch: "epoch".into(),
            after_id: 0,
        };
        let item = PushItem {
            id: 7,
            kind: "interaction_required".into(),
            expires_at: 100,
        };
        let value = payload(&device, &item, "server");
        assert_eq!(
            value["magi"],
            json!({"server_id":"server","data_epoch":"epoch","notification_id":7})
        );
        assert_eq!(value["aps"]["alert"]["loc-key"], "push.input");
        assert!(!value.to_string().contains("private"));
    }
}
