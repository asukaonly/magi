use std::sync::Arc;

use axum::body::Body;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;

use crate::ipc::IpcClient;

pub type HttpClient = Client<HttpConnector, Body>;

#[derive(Clone)]
pub struct ApiState {
    pub python_api_port: u16,
    pub client: HttpClient,
    pub ipc_client: Option<Arc<IpcClient>>,
}
