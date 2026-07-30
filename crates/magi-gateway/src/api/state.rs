use std::path::PathBuf;
use std::sync::Arc;

use crate::ipc::IpcClient;

use super::security::GatewaySecurity;

#[derive(Clone)]
pub struct ApiState {
    pub ipc_client: Arc<IpcClient>,
    pub security: Arc<GatewaySecurity>,
    /// Directory for builtin persona avatar images.
    pub builtin_avatar_dir: Option<PathBuf>,
    /// Directory for user-uploaded avatar images (~/.magi/personalities/avatar).
    pub user_avatar_dir: Option<PathBuf>,
}

impl ApiState {
    pub fn new(ipc_client: Arc<IpcClient>, security: Arc<GatewaySecurity>) -> Self {
        Self {
            ipc_client,
            security,
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
