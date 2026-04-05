use std::sync::Arc;

use axum::body::Body;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use serde_json::Value;
use tokio::sync::broadcast;

use crate::ipc::IpcClient;

pub type HttpClient = Client<HttpConnector, Body>;

/// Notification payload broadcast from the notification bridge to WS clients.
#[derive(Clone, Debug)]
pub struct WsBroadcast {
    pub event: String,
    pub user_id: String,
    pub data: Value,
}

#[derive(Clone)]
pub struct ApiState {
    pub python_api_port: u16,
    pub client: HttpClient,
    pub ipc_client: Option<Arc<IpcClient>>,
    /// Broadcast sender for notification bridge → WebSocket clients.
    pub ws_broadcast: broadcast::Sender<WsBroadcast>,
}
