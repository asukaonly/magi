use std::path::PathBuf;
use std::sync::Arc;

use crate::ipc::IpcClient;

#[derive(Clone)]
pub struct ApiState {
    pub ipc_client: Arc<IpcClient>,
    /// Directory for builtin persona avatar images.
    pub builtin_avatar_dir: Option<PathBuf>,
    /// Directory for user-uploaded avatar images (~/.magi/personalities/avatar).
    pub user_avatar_dir: Option<PathBuf>,
}
