use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, RwLock};

use crate::ipc::{IpcClient, RuntimeConnection};

use super::security::GatewaySecurity;

#[derive(Clone)]
pub struct ApiState {
    pub ipc_client: Arc<RuntimeConnection>,
    pub security: Arc<GatewaySecurity>,
    pub events: Arc<crate::events::EventHub>,
    pub maintenance: Option<Arc<dyn crate::maintenance::MaintenanceControl>>,
    pub storage_ready: Arc<AtomicBool>,
    pub supervisor: Arc<RwLock<magi_service_contract::lifecycle::SupervisorStatus>>,
    /// Directory for builtin persona avatar images.
    pub builtin_avatar_dir: Option<PathBuf>,
    /// Directory for user-uploaded avatar images (~/.magi/personalities/avatar).
    pub user_avatar_dir: Option<PathBuf>,
}

impl ApiState {
    pub fn new(ipc_client: Arc<IpcClient>, security: Arc<GatewaySecurity>) -> Self {
        let state =
            Self::with_runtime(Arc::new(RuntimeConnection::connected(ipc_client)), security);
        state
            .storage_ready
            .store(true, std::sync::atomic::Ordering::Release);
        state
    }

    pub fn with_runtime(
        ipc_client: Arc<RuntimeConnection>,
        security: Arc<GatewaySecurity>,
    ) -> Self {
        Self {
            ipc_client,
            maintenance: None,
            events: Arc::new(crate::events::EventHub::new(
                security.auth.server_id.clone(),
            )),
            security,
            storage_ready: Arc::new(AtomicBool::new(false)),
            supervisor: Arc::new(RwLock::new(Default::default())),
            builtin_avatar_dir: None,
            user_avatar_dir: None,
        }
    }

    pub fn with_avatar_dirs(
        mut self,
        builtin_avatar_dir: Option<PathBuf>,
        user_avatar_dir: Option<PathBuf>,
    ) -> Self {
        self.builtin_avatar_dir = builtin_avatar_dir;
        self.user_avatar_dir = user_avatar_dir;
        self
    }
}
