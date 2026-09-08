//! Replaceable worker connection shared by all gateway routes.

use std::sync::{Arc, RwLock};
use std::time::Duration;

use serde_json::Value;

use super::{protocol::IpcError, IpcClient};

#[derive(Default)]
pub struct RuntimeConnection {
    state: RwLock<ConnectionState>,
}

#[derive(Default)]
struct ConnectionState {
    generation: u64,
    client: Option<Arc<IpcClient>>,
}

impl RuntimeConnection {
    pub fn connected(client: Arc<IpcClient>) -> Self {
        Self {
            state: RwLock::new(ConnectionState {
                generation: 1,
                client: Some(client),
            }),
        }
    }

    /// Retire the previous socket before making the new generation available.
    pub fn replace(&self, client: Option<Arc<IpcClient>>) -> u64 {
        let mut state = self.state.write().unwrap_or_else(|e| e.into_inner());
        if let Some(previous) = state.client.take() {
            previous.disconnect();
        }
        state.generation += 1;
        state.client = client;
        state.generation
    }

    pub fn generation(&self) -> u64 {
        self.state
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .generation
    }

    /// A request keeps its original connection; it never retries on a new worker.
    pub fn current(&self) -> Result<Arc<IpcClient>, IpcError> {
        self.state
            .read()
            .unwrap_or_else(|e| e.into_inner())
            .client
            .as_ref()
            .filter(|client| client.is_connected())
            .cloned()
            .ok_or_else(|| IpcError {
                code: -4,
                message: "Python runtime is unavailable".into(),
            })
    }

    pub async fn request_with_timeout(
        &self,
        method: &str,
        params: Option<Value>,
        timeout: Duration,
    ) -> Result<Value, IpcError> {
        self.current()?
            .request_with_timeout(method, params, timeout)
            .await
    }
}
