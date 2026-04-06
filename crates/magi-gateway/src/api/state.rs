use std::sync::Arc;

use crate::ipc::IpcClient;

#[derive(Clone)]
pub struct ApiState {
    pub ipc_client: Arc<IpcClient>,
}
