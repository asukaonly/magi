use std::sync::Arc;

use serde_json::Value;
use tokio::sync::broadcast;

use crate::ipc::IpcClient;

/// Notification payload broadcast from the notification bridge to WS clients.
#[derive(Clone, Debug)]
pub struct WsBroadcast {
    pub event: String,
    pub user_id: String,
    pub data: Value,
}

#[derive(Clone)]
pub struct ApiState {
    pub ipc_client: Arc<IpcClient>,
    /// Broadcast sender for notification bridge → WebSocket clients.
    pub ws_broadcast: broadcast::Sender<WsBroadcast>,
}
