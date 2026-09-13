//! Producer persistence and network delivery live in the desktop host, independent of WebView timers.

use crate::connections::{
    self,
    protocol::CenterClient,
    runtime::{ConnectionInfo, ConnectionRuntime},
};
use magi_delivery::{DeliveryPolicy, Outbox, QueueStatus, Scope, StreamStatus};
use magi_service_contract::delivery::{
    BackgroundPayload, DeliveryReceipt, EventReceipt, ReceiptStatus,
};
use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager, State};

pub struct DeliveryRuntime {
    outbox: Arc<Mutex<Outbox>>,
    wake: tokio::sync::Notify,
}

impl DeliveryRuntime {
    pub fn open(path: &Path) -> Result<Self, String> {
        Ok(Self {
            outbox: Arc::new(Mutex::new(Outbox::open(path)?)),
            wake: tokio::sync::Notify::new(),
        })
    }

    pub async fn storage<T: Send + 'static>(
        &self,
        work: impl FnOnce(&mut Outbox) -> Result<T, String> + Send + 'static,
    ) -> Result<T, String> {
        let outbox = self.outbox.clone();
        tauri::async_runtime::spawn_blocking(move || {
            let mut queue = outbox
                .lock()
                .map_err(|_| "Background delivery storage unavailable")?;
            work(&mut queue)
        })
        .await
        .map_err(|_| "Background delivery storage interrupted")?
    }
}

fn now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(i64::MAX as u128) as i64
}
fn scope(info: &ConnectionInfo) -> Scope {
    Scope {
        profile_id: info.profile_id.clone(),
        server_id: info.server_id.clone(),
        data_epoch: info.data_epoch.clone(),
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EnqueueRequest {
    scope: Scope,
    generation: u64,
    event_id: String,
    stream: String,
    payload: BackgroundPayload,
    policy: DeliveryPolicy,
}

fn validate_scope(
    state: &ConnectionRuntime,
    expected: &Scope,
    generation: u64,
) -> Result<(), String> {
    let (current, info) = state.snapshot()?;
    if current != generation
        || expected.profile_id != info.profile_id
        || expected.server_id != info.server_id
    {
        return Err("Background delivery connection changed".into());
    }
    Ok(())
}

#[tauri::command]
pub async fn enqueue_background_event(
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, DeliveryRuntime>,
    request: EnqueueRequest,
) -> Result<bool, String> {
    let _operation = state.operation.lock().await;
    validate_scope(&state, &request.scope, request.generation)?;
    let accepted = delivery
        .storage(move |queue| {
            queue.enqueue(
                &request.scope,
                &request.stream,
                &request.event_id,
                request.payload,
                request.policy,
                now(),
            )
        })
        .await?;
    delivery.wake.notify_one();
    Ok(accepted)
}

#[derive(Serialize)]
pub struct DeliveryStatus {
    queue: QueueStatus,
    notification_read_ids: Vec<i64>,
}

#[tauri::command]
pub async fn background_delivery_status(
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, DeliveryRuntime>,
    scope: Scope,
    generation: u64,
) -> Result<DeliveryStatus, String> {
    let _operation = state.operation.lock().await;
    validate_scope(&state, &scope, generation)?;
    delivery
        .storage(move |queue| {
            Ok(DeliveryStatus {
                queue: queue.status(&scope)?,
                notification_read_ids: queue.pending_notification_reads(&scope)?,
            })
        })
        .await
}

#[tauri::command]
pub async fn retry_background_delivery(
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, DeliveryRuntime>,
    scope: Scope,
    generation: u64,
) -> Result<(), String> {
    let _operation = state.operation.lock().await;
    validate_scope(&state, &scope, generation)?;
    delivery
        .storage(move |queue| queue.retry_failed(&scope))
        .await?;
    delivery.wake.notify_one();
    Ok(())
}

#[tauri::command]
pub async fn background_delivery_streams(
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, DeliveryRuntime>,
    scope: Scope,
    generation: u64,
) -> Result<Vec<StreamStatus>, String> {
    let _operation = state.operation.lock().await;
    validate_scope(&state, &scope, generation)?;
    delivery.storage(move |queue| queue.streams(&scope)).await
}

#[tauri::command]
pub async fn recover_background_stream(
    state: State<'_, ConnectionRuntime>,
    delivery: State<'_, DeliveryRuntime>,
    scope: Scope,
    generation: u64,
    stream: String,
    discard: bool,
) -> Result<(), String> {
    let _operation = state.operation.lock().await;
    validate_scope(&state, &scope, generation)?;
    delivery
        .storage(move |queue| queue.recover_stream(&scope, &stream, discard, now()))
        .await?;
    delivery.wake.notify_one();
    Ok(())
}

pub fn start(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut last_scope_check = std::time::Instant::now() - Duration::from_secs(30);
        loop {
            let delivery = app.state::<DeliveryRuntime>();
            tokio::select! { _ = tokio::time::sleep(Duration::from_secs(1)) => {}, _ = delivery.wake.notified() => {} }
            let check_scope = last_scope_check.elapsed() >= Duration::from_secs(30);
            if check_scope {
                last_scope_check = std::time::Instant::now();
            }
            if let Err(error) = send_next(&app, check_scope).await {
                log::warn!("Background delivery paused: {error}");
                tokio::time::sleep(Duration::from_secs(10)).await;
            }
        }
    });
}

async fn send_next(app: &AppHandle, check_scope: bool) -> Result<(), String> {
    let state = app.state::<ConnectionRuntime>();
    let Ok((generation, mut info)) = state.snapshot() else {
        return Ok(());
    };
    let delivery = app.state::<DeliveryRuntime>();
    let profile = info.profile_id.clone();
    if !check_scope
        && !delivery
            .storage(move |queue| queue.has_work(&profile, now()))
            .await?
    {
        return Ok(());
    }
    if info.mode == "remote"
        && info
            .expires_at_ms
            .is_none_or(|expiry| expiry < now() + 30_000)
    {
        if connections::runtime::renew_center_session(
            app.state(),
            app.state(),
            info.profile_id.clone(),
        )
        .await
        .is_err()
        {
            let profile = info.profile_id.clone();
            delivery
                .storage(move |queue| {
                    queue.defer_profile(&profile, now(), "authorization_unavailable")
                })
                .await?;
            return Ok(());
        }
        let (current, refreshed) = state.snapshot()?;
        if current != generation {
            return Ok(());
        }
        info = refreshed;
    }
    let client = if info.mode == "local" {
        CenterClient::local(&info.base_url)?
    } else {
        CenterClient::remote(&info.base_url)?
    };
    let initial_scope = scope(&info);
    let server = match client.info(&info.session_token).await {
        Ok(server) => server,
        Err(_) => {
            delivery
                .storage(move |queue| {
                    queue.defer_profile(&initial_scope.profile_id, now(), "connection_unavailable")
                })
                .await?;
            return Ok(());
        }
    };
    if !state.is_current(generation) {
        return Ok(());
    }
    if server.server_id != info.server_id {
        return Err("Server identity changed; reconnect explicitly".into());
    }
    info.data_epoch = server.maintenance.data_epoch;
    let destination = scope(&info);
    let batch = delivery
        .storage(move |queue| {
            queue.retire_epochs(
                &destination.profile_id,
                &destination.server_id,
                &destination.data_epoch,
            )?;
            queue.claim(&destination, now())
        })
        .await?;
    if batch.events.is_empty() {
        return Ok(());
    }
    // A switch never changes this request's address, identity or payload. Its ACK only removes these IDs.
    let response = client.deliver(&info.session_token, &batch).await;
    if matches!(&response, Err(error) if error.code == "authorization_required")
        && state.is_current(generation)
        && info.mode == "remote"
    {
        let _ =
            connections::runtime::renew_center_session(app.state(), app.state(), info.profile_id)
                .await;
    }
    delivery
        .storage(move |queue| match response {
            Ok(receipt) => match queue.acknowledge(&batch, &receipt, now()) {
                Ok(()) => Ok(()),
                Err(_) => queue.retry(&batch, now(), "invalid_receipt", None),
            },
            Err(failure) if failure.permanent => {
                let receipt = DeliveryReceipt {
                    server_id: batch.server_id.clone(),
                    data_epoch: batch.data_epoch.clone(),
                    receipts: batch
                        .events
                        .iter()
                        .map(|event| EventReceipt {
                            event_id: event.event_id.clone(),
                            status: ReceiptStatus::Rejected,
                            code: failure.code.into(),
                        })
                        .collect(),
                };
                queue.acknowledge(&batch, &receipt, now())
            }
            Err(failure) => queue.retry(&batch, now(), failure.code, failure.retry_after_ms),
        })
        .await
}
