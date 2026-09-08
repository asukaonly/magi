use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{future::Future, pin::Pin};

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MaintenanceStatus {
    pub version: u8,
    pub operation_id: Option<String>,
    pub phase: String,
    pub data_epoch: String,
    pub result: Option<Value>,
    pub error: Option<String>,
}

pub trait MaintenanceControl: Send + Sync {
    fn status(&self) -> MaintenanceStatus;
    fn begin_clear(
        &self,
        operation_id: String,
    ) -> Pin<Box<dyn Future<Output = Result<MaintenanceStatus, String>> + Send + '_>>;
}
